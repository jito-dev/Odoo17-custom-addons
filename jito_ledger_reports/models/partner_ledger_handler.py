# -*- coding: utf-8 -*-

from collections import defaultdict

from odoo import api, fields, models, _
from odoo.exceptions import UserError


SCOPE_MANAGEMENT = 'management'
SCOPE_FAAP = 'faap'
SCOPE_COMBINED = 'combined'

# Per-scope source-model registry. Each tuple is (source_label,
# model_name). Order matters for COMBINED — drives the iteration order
# of read_group calls and the source ordering tag.
SCOPE_SOURCES = {
    SCOPE_MANAGEMENT: [('mgmt', 'jito.ledger.move.line')],
    SCOPE_FAAP: [('faap', 'jito.ledger.statutory.view')],
    SCOPE_COMBINED: [
        ('mgmt', 'jito.ledger.move.line'),
        ('faap', 'jito.ledger.statutory.view'),
    ],
}


class JitoPartnerLedgerCustomHandler(models.AbstractModel):
    """Custom handler for the Management Partner Ledger report (17.0.2.0.0).

    Mirrors stock ``account_reports.partner_ledger_report`` shape but
    runs against ``jito.ledger.move.line`` (HLD: parallel-record model;
    no FK into stock account.move*). Each partner shows aggregated
    debit / credit / balance for the period, with drill-down to the
    underlying journal items.

    17.0.3.0.0 — adds the ``jito_data_scope`` option with three values:
    ``management`` (default; reads jito.ledger.move.line),
    ``faap`` (reads jito.ledger.statutory.view — LL projected through
    FAAP mirrors), or ``combined`` (both sources unioned per partner).
    The scope is normally seeded by the action's
    ``default_jito_data_scope`` context, since stock account.report
    doesn't render custom selection filters without OWL extension.
    """

    _name = 'jito.ledger.partner.ledger.report.handler'
    _inherit = ['account.report.custom.handler', 'jito.ledger.report.handler.base']
    _description = 'Management Partner Ledger Custom Handler'

    EXPAND_FUNC = '_report_expand_unfoldable_line_jito_partner_ledger'

    # ---- options --------------------------------------------------------

    def _custom_options_initializer(self, report, options, previous_options=None):
        """Seed report options:

          * ``jito_rate_policy`` — same as Trial Balance (FR-23 FX policy).
          * ``jito_data_scope`` — 17.0.3.0.0 source scope. Resolution
            order: action context (``default_jito_data_scope``) →
            previous_options → ``management`` default.

            **Context wins over previous_options** so each menu click
            (Management / FAAP Projection / Combined) acts as a fresh
            entry point that resets the scope. Without this, navigating
            from Management → Combined would silently re-render
            Management because the previous render's option survives in
            ``previous_options``.
        """
        super()._custom_options_initializer(report, options, previous_options=previous_options)
        prev = previous_options or {}
        options['jito_rate_policy'] = (
            prev.get('jito_rate_policy') or 'period_end'
        )
        scope = (
            self.env.context.get('default_jito_data_scope')
            or prev.get('jito_data_scope')
            or SCOPE_MANAGEMENT
        )
        if scope not in SCOPE_SOURCES:
            scope = SCOPE_MANAGEMENT
        options['jito_data_scope'] = scope

    # ---- main report generation -----------------------------------------

    def _dynamic_lines_generator(self, report, options, all_column_groups_expression_totals, warnings=None):
        """Build one unfoldable parent row per partner that has activity
        across the selected source(s) in the period. Children (journal
        items) are fetched on-demand by the expand callback.
        """
        company = self.env.company
        company_currency = company.currency_id

        date_from, date_to = self._resolve_date_range(options)
        include_drafts = bool(options.get('show_draft') or options.get('all_entries'))
        rate_date = self._resolve_rate_date(options, date_to)
        rate_map = self._build_rate_map(rate_date, company)
        partner_filter = self._partner_filter_from_options(options)
        sources = SCOPE_SOURCES[options['jito_data_scope']]

        # Per-partner period sums (debit/credit in company currency),
        # aggregated across all selected sources.
        per_partner_period = defaultdict(lambda: {'debit': 0.0, 'credit': 0.0})
        for _src_tag, model_name in sources:
            for partner_id, debit_inc, credit_inc in self._query_partner_period(
                    options, date_from, date_to, include_drafts,
                    rate_map, model_name, partner_filter):
                per_partner_period[partner_id]['debit'] += debit_inc
                per_partner_period[partner_id]['credit'] += credit_inc

        # Initial balance per partner (sums across all selected sources).
        partner_ids = list(per_partner_period.keys())
        per_partner_initial = self._compute_initial_balances(
            options, date_from, partner_ids, include_drafts, rate_map, sources,
        )

        Partner = self.env['res.partner']
        partners = Partner.browse(partner_ids).sorted('display_name')

        lines = []
        total_debit = total_credit = 0.0
        for partner in partners:
            tots = per_partner_period[partner.id]
            debit = company_currency.round(tots['debit'])
            credit = company_currency.round(tots['credit'])
            initial = company_currency.round(per_partner_initial.get(partner.id, 0.0))
            balance = company_currency.round(initial + debit - credit)
            total_debit += debit
            total_credit += credit
            lines.append((0, {
                'id': report._get_generic_line_id('res.partner', partner.id),
                'name': partner.display_name or _('Unnamed partner'),
                'level': 2,
                'unfoldable': True,
                'unfolded': bool(options.get('unfold_all')),
                'expand_function': self.EXPAND_FUNC,
                'columns': self._parent_row_columns(
                    company_currency, debit, credit, balance,
                ),
                'caret_options': False,
            }))

        lines.append((0, {
            'id': report._get_generic_line_id(False, False, markup='total'),
            'name': _('Total'),
            'level': 1,
            'class': 'total',
            'columns': self._parent_row_columns(
                company_currency,
                company_currency.round(total_debit),
                company_currency.round(total_credit),
                company_currency.round(total_debit - total_credit),
            ),
        }))
        return lines

    def _parent_row_columns(self, company_currency, debit, credit, balance):
        """Parent / total rows: amount_currency cell is blank (rolled-up
        partners are inherently multi-currency).
        """
        return [
            self._make_money_column(company_currency, debit),
            self._make_money_column(company_currency, credit),
            {'name': '', 'class': 'number'},
            self._make_money_column(company_currency, balance),
        ]

    # ---- expand callback ------------------------------------------------

    def _report_expand_unfoldable_line_jito_partner_ledger(
            self, line_dict_id, groupby, options, progress, offset,
            unfold_all_batch_data=None):
        """Drill-down: returns the partner's journal items from all
        selected sources, merged by date, with a running balance that
        starts at the partner's initial balance and accumulates.
        """
        report = self.env['account.report'].browse(options.get('report_id'))
        if not report:
            report = self.env.ref(
                'jito_ledger_reports.management_partner_ledger_report',
                raise_if_not_found=False,
            )
        if not report:
            raise UserError(_(
                "Partner Ledger report record not found. Re-upgrade "
                "the jito_ledger_reports module."
            ))

        markup, model, partner_id = report._parse_line_id(line_dict_id)[-1]
        if model != 'res.partner':
            raise UserError(_(
                "Wrong ID for partner ledger line to expand: %s",
                line_dict_id,
            ))

        company = self.env.company
        company_currency = company.currency_id
        date_from, date_to = self._resolve_date_range(options)
        include_drafts = bool(options.get('show_draft') or options.get('all_entries'))
        rate_date = self._resolve_rate_date(options, date_to)
        rate_map = self._build_rate_map(rate_date, company)
        sources = SCOPE_SOURCES[options['jito_data_scope']]

        initial = self._compute_initial_balances(
            options, date_from, [partner_id], include_drafts,
            rate_map, sources,
        ).get(partner_id, 0.0)
        running = company_currency.round(initial)

        lines = []
        if not offset:
            lines.append({
                'id': report._get_generic_line_id(
                    'res.partner', partner_id,
                    markup='initial', parent_line_id=line_dict_id,
                ),
                'name': _('Initial Balance'),
                'level': 3,
                'parent_id': line_dict_id,
                'class': 'o_account_reports_initial_balance',
                'columns': [
                    self._make_money_column(company_currency, 0.0),
                    self._make_money_column(company_currency, 0.0),
                    {'name': '', 'class': 'number'},
                    self._make_money_column(company_currency, running),
                ],
            })

        # Collect rows from each selected source, then sort by date.
        records = []  # list of (date, src_tag, record_dict)
        for src_tag, model_name in sources:
            records.extend(
                self._fetch_partner_lines(
                    options, date_from, date_to, include_drafts,
                    model_name, partner_id, src_tag,
                )
            )
        records.sort(key=lambda r: (r['date'] or date_from, r['record_id']))

        is_combined = options['jito_data_scope'] == SCOPE_COMBINED
        for rec in records:
            currency = rec['currency_id']
            net_tx = rec['amount_currency']
            # LL sources provide company_signed directly (debit−credit,
            # already in company currency). MGT sources leave it None
            # and we translate via rate_map.
            if rec['company_signed'] is not None:
                net_company = company_currency.round(rec['company_signed'])
            else:
                net_company = company_currency.round(
                    net_tx * rate_map.get(currency.id if currency else 0, 1.0)
                )
            debit = net_company if net_company > 0 else 0.0
            credit = -net_company if net_company < 0 else 0.0
            running = company_currency.round(running + net_company)
            # "Amount Currency" column: only meaningful when the line
            # is in a non-company currency. Else leave blank — Debit /
            # Credit already convey the company-currency value.
            if currency and currency.id != company_currency.id and net_tx:
                amt_cur_col = {
                    'name': currency.format(net_tx),
                    'no_format': net_tx,
                    'class': 'number',
                }
            else:
                amt_cur_col = {'name': '', 'class': 'number'}
            lines.append({
                'id': report._get_generic_line_id(
                    rec['record_model'], rec['record_id'],
                    parent_line_id=line_dict_id,
                ),
                'name': self._format_child_label(rec, is_combined),
                'level': 3,
                'parent_id': line_dict_id,
                'caret_options': False,
                'columns': [
                    self._make_money_column(company_currency, debit),
                    self._make_money_column(company_currency, credit),
                    amt_cur_col,
                    self._make_money_column(company_currency, running),
                ],
            })

        return {
            'lines': lines,
            'offset_increment': len(records),
            'has_more': False,
            'progress': {},
        }

    def _format_child_label(self, rec, is_combined):
        """Compact, scan-friendly label for a drill-down row.

        Layout: ``YYYY-MM-DD · [TAG] · JOURNAL · ACCOUNT · REF | MOVE``.
        The source tag is only included for combined scope; single-source
        reports omit it since it's redundant. Empty segments are dropped.
        """
        date_str = fields.Date.to_string(rec['date']) if rec['date'] else ''
        parts = [date_str]
        if is_combined:
            parts.append('[%s]' % rec['src_tag'].upper())
        if rec['journal_code']:
            parts.append(rec['journal_code'])
        if rec['account_label'].strip():
            parts.append(rec['account_label'].strip())
        if rec['ref']:
            parts.append(rec['ref'])
        label = ' · '.join(p for p in parts if p)
        if rec['display_name']:
            label = '%s | %s' % (label, rec['display_name'])
        return label

    # ---- per-source readers ---------------------------------------------

    def _query_partner_period(self, options, date_from, date_to,
                              include_drafts, rate_map, model_name,
                              partner_filter):
        """Generator: yields ``(partner_id, debit_inc, credit_inc)`` in
        **company currency** for one source model.

        Branches by source:
          * LL sources (``jito.ledger.statutory.view``,
            ``account.move.line``) — sum `debit` / `credit` directly.
            They're already in company currency; no rate_map needed and
            no risk of being silently dropped when ``currency_id`` is
            False on legacy lines.
          * Management source (``jito.ledger.move.line``) — sum
            `amount_currency` per ``(partner, currency)`` and translate
            via rate_map. The MGT model requires ``currency_id`` so the
            falsy-skip clause is safe.
        """
        domain = self._build_domain(
            options, date_from, date_to,
            model_name=model_name, include_drafts=include_drafts,
        ) + [('partner_id', '!=', False)]
        if partner_filter:
            domain.append(('partner_id', 'in', partner_filter))
        Line = self.env[model_name]
        if model_name in ('jito.ledger.statutory.view', 'account.move.line'):
            groups = Line.read_group(
                domain=domain,
                fields=['partner_id', 'debit:sum', 'credit:sum'],
                groupby=['partner_id'],
                lazy=False,
            )
            for grp in groups:
                partner_id = grp.get('partner_id') and grp['partner_id'][0]
                if not partner_id:
                    continue
                yield partner_id, grp.get('debit') or 0.0, grp.get('credit') or 0.0
            return
        # MGT source — translate amount_currency per currency.
        groups = Line.read_group(
            domain=domain,
            fields=['partner_id', 'currency_id', 'amount_currency:sum'],
            groupby=['partner_id', 'currency_id'],
            lazy=False,
        )
        for grp in groups:
            partner_id = grp.get('partner_id') and grp['partner_id'][0]
            currency_id = grp.get('currency_id') and grp['currency_id'][0]
            net_tx = grp.get('amount_currency') or 0.0
            if not partner_id or not currency_id:
                continue
            net_company = net_tx * rate_map.get(currency_id, 1.0)
            if net_company > 0:
                yield partner_id, net_company, 0.0
            elif net_company < 0:
                yield partner_id, 0.0, -net_company

    def _compute_initial_balances(self, options, date_from, partner_ids,
                                  include_drafts, rate_map, sources):
        """Sum each partner's signed company-currency amount for moves
        dated *before* the period, across all selected source models.
        Returns ``{partner_id: signed_balance}`` (positive = debit).

        Source-aware branching same as ``_query_partner_period``: LL
        uses ``debit - credit`` (already company currency); MGT uses
        translated ``amount_currency``.
        """
        out = defaultdict(float)
        if not partner_ids:
            return out
        for _src_tag, model_name in sources:
            Line = self.env[model_name]
            domain = self._initial_domain(model_name, date_from,
                                          include_drafts, partner_ids)
            if model_name in ('jito.ledger.statutory.view', 'account.move.line'):
                groups = Line.read_group(
                    domain=domain,
                    fields=['partner_id', 'debit:sum', 'credit:sum'],
                    groupby=['partner_id'],
                    lazy=False,
                )
                for grp in groups:
                    pid = grp.get('partner_id') and grp['partner_id'][0]
                    if not pid:
                        continue
                    out[pid] += (grp.get('debit') or 0.0) - (grp.get('credit') or 0.0)
                continue
            # MGT source.
            groups = Line.read_group(
                domain=domain,
                fields=['partner_id', 'currency_id', 'amount_currency:sum'],
                groupby=['partner_id', 'currency_id'],
                lazy=False,
            )
            for grp in groups:
                pid = grp.get('partner_id') and grp['partner_id'][0]
                cid = grp.get('currency_id') and grp['currency_id'][0]
                if not pid or not cid:
                    continue
                out[pid] += (grp.get('amount_currency') or 0.0) * rate_map.get(cid, 1.0)
        return out

    def _initial_domain(self, model_name, date_from, include_drafts,
                        partner_ids):
        """Pre-period domain for a given source model. Mirrors
        ``_build_domain`` shape but with ``date < date_from`` and a
        ``partner_id IN partner_ids`` clause.
        """
        date_str = fields.Date.to_string(date_from)
        company_clause = ('company_id', 'in', self.env.companies.ids)
        common = [
            ('date', '<', date_str),
            company_clause,
            ('partner_id', 'in', partner_ids),
        ]
        if model_name == 'jito.ledger.move.line':
            domain = [('move_id.is_voided', '=', False)] + common
            if not include_drafts:
                domain.insert(0, ('move_state', '=', 'posted'))
            return domain
        if model_name == 'jito.ledger.statutory.view':
            return [('state', '=', 'posted')] + common
        if model_name == 'account.move.line':
            domain = list(common)
            if not include_drafts:
                domain.insert(0, ('parent_state', '=', 'posted'))
            return domain
        raise ValueError("Unsupported source model: %r" % (model_name,))

    def _fetch_partner_lines(self, options, date_from, date_to,
                             include_drafts, model_name, partner_id, src_tag):
        """Return a list of dicts with the fields the expand callback
        needs, normalised across source models.

        Keys: date, currency_id, amount_currency, company_signed,
        journal_code, account_label, ref, display_name, record_model,
        record_id, src_tag.

        ``company_signed`` is the signed amount **already in company
        currency** (positive = debit). When non-None, the expand
        callback uses it directly and skips the rate_map. LL sources
        always populate it from ``debit - credit``; MGT leaves it None
        so the rate_map translation kicks in.
        """
        domain = self._build_domain(
            options, date_from, date_to,
            model_name=model_name, include_drafts=include_drafts,
        ) + [('partner_id', '=', partner_id)]
        Line = self.env[model_name]
        records = Line.search(domain, order='date, id')
        out = []
        if model_name == 'jito.ledger.move.line':
            for r in records:
                out.append({
                    'date': r.date,
                    'currency_id': r.currency_id,
                    'amount_currency': r.amount_currency or 0.0,
                    'company_signed': None,
                    'journal_code': r.journal_id.code or r.journal_id.name or '',
                    'account_label': '%s %s' % (
                        r.account_id.code or '', r.account_id.name or '',
                    ),
                    'ref': r.move_ref or '',
                    'display_name': r.move_name or r.name or '',
                    'record_model': 'jito.ledger.move.line',
                    'record_id': r.id,
                    'src_tag': src_tag,
                })
        elif model_name == 'jito.ledger.statutory.view':
            company_cur = self.env.company.currency_id
            for r in records:
                faap_acct = r.faap_account_id
                acct_label = (
                    '%s %s' % (faap_acct.code or '', faap_acct.name or '')
                    if faap_acct else
                    '%s %s' % (r.account_id.code or '', r.account_id.name or '')
                )
                out.append({
                    'date': r.date,
                    'currency_id': r.currency_id or company_cur,
                    'amount_currency': r.amount_currency or 0.0,
                    'company_signed': (r.debit or 0.0) - (r.credit or 0.0),
                    'journal_code': r.journal_id.code or r.journal_id.name or '',
                    'account_label': acct_label,
                    'ref': (r.move_id.ref or '') if r.move_id else '',
                    'display_name': (r.move_id.name or r.name or '')
                                    if r.move_id else (r.name or ''),
                    'record_model': 'jito.ledger.statutory.view',
                    'record_id': r.id,
                    'src_tag': src_tag,
                })
        elif model_name == 'account.move.line':
            company_cur = self.env.company.currency_id
            for r in records:
                out.append({
                    'date': r.date,
                    'currency_id': r.currency_id or company_cur,
                    'amount_currency': r.amount_currency or 0.0,
                    'company_signed': (r.debit or 0.0) - (r.credit or 0.0),
                    'journal_code': r.journal_id.code or r.journal_id.name or '',
                    'account_label': '%s %s' % (
                        r.account_id.code or '', r.account_id.name or '',
                    ),
                    'ref': r.move_id.ref or '',
                    'display_name': r.move_id.name or r.name or '',
                    'record_model': 'account.move.line',
                    'record_id': r.id,
                    'src_tag': src_tag,
                })
        return out

    def _partner_filter_from_options(self, options):
        """Read the partner filter (selected partner IDs) from report
        options. Stock's report engine drops it under
        ``options['partner_ids']`` when ``filter_partner=True`` on the
        report record.
        """
        ids = options.get('partner_ids') or []
        if not ids:
            return None
        return [pid for pid in ids if isinstance(pid, int)]

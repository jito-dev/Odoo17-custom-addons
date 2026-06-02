# -*- coding: utf-8 -*-

from collections import defaultdict

from odoo import fields, models, _
from odoo.exceptions import UserError


SCOPE_MANAGEMENT = 'management'
SCOPE_COMBINED = 'combined'

# Per-scope source-model registry. Each tuple is (src_tag, model_name).
# Order matters for COMBINED — drives the merge ordering when child rows
# from multiple sources collide on the same date.
#
# 17.0.6.0.0 — the COMBINED scope unions the NL storage
# (`jito.ledger.move.line` — which holds both NL and EXT entries via
# `entry_type` discriminator) with `jito.ledger.statutory.view` (the
# FAAP projection of stock `account.move.line` onto NL accounts via
# `jito.ledger.account.statutory_account_id`). Hence the user-facing
# label "LL + NL + EXT": LL data flows through the FAAP view; NL+EXT
# come from the parallel-record table. LL accounts without a
# `statutory_account_id` inverse mapping are NOT included — see
# GUIDANCE.md "Common pitfalls".
SCOPE_SOURCES = {
    SCOPE_MANAGEMENT: [('mgmt', 'jito.ledger.move.line')],
    SCOPE_COMBINED: [
        ('mgmt', 'jito.ledger.move.line'),
        ('faap', 'jito.ledger.statutory.view'),
    ],
}


class JitoGeneralLedgerCustomHandler(models.AbstractModel):
    """Custom handler for the Management ("Non-Leading") General Ledger
    report (17.0.5.0.0; multi-source scope added 17.0.6.0.0).

    Mirrors stock ``account_reports`` General Ledger shape, running
    against ``jito.ledger.move.line`` (NL+EXT) and optionally
    ``jito.ledger.statutory.view`` (LL via FAAP projection) when the
    ``combined`` scope is selected. Parent rows aggregate by
    ``jito.ledger.account``; drill-down yields the journal items in
    date order with a running balance.
    """

    _name = 'jito.ledger.general.ledger.report.handler'
    _inherit = ['account.report.custom.handler', 'jito.ledger.report.handler.base']
    _description = 'Management General Ledger Custom Handler'

    EXPAND_FUNC = '_report_expand_unfoldable_line_jito_general_ledger'

    # ---- caret options --------------------------------------------------

    def _caret_options_initializer(self):
        """Per-line caret-dropdown actions.

        Stock account_reports auto-appends an "Annotate" entry to any
        line that has caret options, so we only declare the explicit
        choices here.

        * ``jito.ledger.account`` (account parent rows):
            **Open** + **Journal Items**.
        * ``jito.ledger.move.line`` / ``jito.ledger.statutory.view`` /
          ``account.move.line`` (child line models — the latter two
          surface in COMBINED scope): **View Journal Entry** with
          ``action_param='move_id'``.
        """
        view_je = {
            'name': _("View Journal Entry"),
            'action': 'caret_option_open_record_form',
            'action_param': 'move_id',
        }
        return {
            'jito.ledger.account': [
                {'name': _("Open"), 'action': 'caret_option_open_record_form'},
                {'name': _("Journal Items"),
                 'action': 'caret_option_open_account_journal_items'},
            ],
            'jito.ledger.move.line': [view_je],
            'jito.ledger.statutory.view': [view_je],
            'account.move.line': [view_je],
        }

    def caret_option_open_account_journal_items(self, options, params):
        """Caret action: open the ML Journal Items list filtered to the
        clicked account row. Dispatched by
        ``account.report.dispatch_report_action`` because the handler
        defines this method.
        """
        report = self.env['account.report'].browse(options['report_id'])
        _model, account_id = report._get_model_info_from_id(params['line_id'])
        action = self.env['ir.actions.act_window']._for_xml_id(
            'jito_ledger_nl.action_jito_ledger_move_line'
        )
        action['domain'] = [('account_id', '=', account_id)]
        action['context'] = {
            'search_default_account_id': account_id,
            'search_default_state_posted': 1,
        }
        return action

    # ---- options --------------------------------------------------------

    def _custom_options_initializer(self, report, options, previous_options=None):
        """Seed report options:

          * ``jito_rate_policy`` — FR-23 FX policy.
          * ``jito_data_scope`` — 17.0.6.0.0 source scope. Resolution
            order: action context (``default_jito_data_scope``) →
            previous_options → ``management`` default. Context wins
            over previous_options so each menu click (Non-Leading
            Ledger vs LL+NL+EXT) acts as a fresh entry point that
            resets the scope.
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
        """Build one unfoldable parent row per ``jito.ledger.account``
        with activity in the period across all selected source models.
        Children are fetched on-demand by the expand callback.
        """
        company = self.env.company
        company_currency = company.currency_id

        date_from, date_to = self._resolve_date_range(options)
        include_drafts = bool(options.get('show_draft') or options.get('all_entries'))
        rate_date = self._resolve_rate_date(options, date_to)
        rate_map = self._build_rate_map(rate_date, company)
        sources = SCOPE_SOURCES[options['jito_data_scope']]

        per_account_period = defaultdict(lambda: {'debit': 0.0, 'credit': 0.0})
        for _src_tag, model_name in sources:
            for account_id, debit_inc, credit_inc in self._query_account_period(
                    options, date_from, date_to, include_drafts,
                    rate_map, model_name):
                per_account_period[account_id]['debit'] += debit_inc
                per_account_period[account_id]['credit'] += credit_inc

        account_ids = list(per_account_period.keys())
        per_account_initial = self._compute_initial_balances(
            options, date_from, account_ids, include_drafts, rate_map, sources,
        )

        # 17.0.7.0.0 — bucket accounts by category so the GL emits per-
        # category header / subtotal rows around each group of account
        # rows. Uncategorized accounts fall into a trailing
        # "(Uncategorized)" bucket. Account drill-down (child journal
        # items) is unaffected — categories are a parent-row layout
        # concern only.
        Account = self.env['jito.ledger.account']
        accounts = Account.browse(account_ids)
        buckets = self._bucket_accounts_by_category(accounts)

        lines = []
        total_debit = total_credit = 0.0
        empty_meta_cols = [
            {'name': '', 'class': 'date'},
            {'name': '', 'class': 'text'},
            {'name': '', 'class': 'text'},
        ]
        empty_amt_cur = {'name': '', 'class': 'text'}
        for bucket in buckets:
            cat = bucket['category']
            cat_name = cat.name if cat else _("(Uncategorized)")
            cat_debit = 0.0
            cat_credit = 0.0
            cat_balance = 0.0

            lines.append((0, {
                'id': report._get_generic_line_id(
                    'jito.ledger.account.category',
                    cat.id if cat else 0,
                    markup='category_header',
                ),
                'name': cat_name,
                'level': 1,
                'columns': [
                    *empty_meta_cols,
                    {'name': '', 'class': 'number'},
                    {'name': '', 'class': 'number'},
                    empty_amt_cur,
                    {'name': '', 'class': 'number'},
                ],
            }))

            for account in bucket['accounts']:
                tots = per_account_period[account.id]
                debit = company_currency.round(tots['debit'])
                credit = company_currency.round(tots['credit'])
                initial = company_currency.round(per_account_initial.get(account.id, 0.0))
                balance = company_currency.round(initial + debit - credit)
                cat_debit += debit
                cat_credit += credit
                cat_balance += balance
                total_debit += debit
                total_credit += credit
                lines.append((0, {
                    'id': report._get_generic_line_id('jito.ledger.account', account.id),
                    'name': '%s %s' % (account.code or '', account.name or ''),
                    'level': 2,
                    'unfoldable': True,
                    'unfolded': bool(options.get('unfold_all')),
                    'expand_function': self.EXPAND_FUNC,
                    'columns': self._parent_row_columns(
                        company_currency, debit, credit, balance,
                    ),
                    'caret_options': 'jito.ledger.account',
                }))

            cat_debit_r = company_currency.round(cat_debit)
            cat_credit_r = company_currency.round(cat_credit)
            cat_balance_r = company_currency.round(cat_balance)
            lines.append((0, {
                'id': report._get_generic_line_id(
                    'jito.ledger.account.category',
                    cat.id if cat else 0,
                    markup='category_total',
                ),
                'name': _("Subtotal %s", cat_name),
                'level': 1,
                'class': 'total',
                'columns': self._parent_row_columns(
                    company_currency, cat_debit_r, cat_credit_r, cat_balance_r,
                ),
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
        """Parent / total rows.

        Column layout: Date, Communication, Partner, Debit, Credit,
        Amount Currency, Balance. The four metadata cells are blank on
        rolled-up rows.
        """
        return [
            {'name': '', 'class': 'date'},
            {'name': '', 'class': 'text'},
            {'name': '', 'class': 'text'},
            self._make_money_column(company_currency, debit),
            self._make_money_column(company_currency, credit),
            {'name': '', 'class': 'text'},
            self._make_money_column(company_currency, balance),
        ]

    # ---- expand callback ------------------------------------------------

    def _report_expand_unfoldable_line_jito_general_ledger(
            self, line_dict_id, groupby, options, progress, offset,
            unfold_all_batch_data=None):
        """Drill-down: returns the account's journal items in the
        period (across all selected sources), merged by date, with a
        running balance that starts at the initial balance and
        accumulates per line.

        In COMBINED scope, each child row's label is prefixed with
        ``[MGT]`` / ``[FAAP]`` so the user can tell which side a line
        came from.
        """
        report = self.env['account.report'].browse(options.get('report_id'))
        if not report:
            report = self.env.ref(
                'jito_ledger_reports.management_general_ledger_report',
                raise_if_not_found=False,
            )
        if not report:
            raise UserError(_(
                "General Ledger report record not found. Re-upgrade "
                "the jito_ledger_reports module."
            ))

        markup, model, account_id = report._parse_line_id(line_dict_id)[-1]
        if model != 'jito.ledger.account':
            raise UserError(_(
                "Wrong ID for general ledger line to expand: %s",
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
            options, date_from, [account_id], include_drafts, rate_map, sources,
        ).get(account_id, 0.0)
        running = company_currency.round(initial)

        lines = []
        if not offset:
            lines.append({
                'id': report._get_generic_line_id(
                    'jito.ledger.account', account_id,
                    markup='initial', parent_line_id=line_dict_id,
                ),
                'name': _('Initial Balance'),
                'level': 3,
                'parent_id': line_dict_id,
                'class': 'o_account_reports_initial_balance',
                'columns': [
                    {'name': '', 'class': 'date'},
                    {'name': '', 'class': 'text'},
                    {'name': '', 'class': 'text'},
                    self._make_money_column(company_currency, 0.0),
                    self._make_money_column(company_currency, 0.0),
                    {'name': '', 'class': 'text'},
                    self._make_money_column(company_currency, running),
                ],
            })

        records = []
        for src_tag, model_name in sources:
            records.extend(self._fetch_account_lines(
                options, date_from, date_to, include_drafts,
                model_name, account_id, src_tag,
            ))
        records.sort(key=lambda r: (r['date'] or date_from, r['record_id']))

        is_combined = options['jito_data_scope'] == SCOPE_COMBINED
        for rec in records:
            currency = rec['currency_id']
            net_tx = rec['amount_currency']
            # LL sources provide ``company_signed`` directly (already
            # company currency). NL leaves it None → translate via
            # rate_map.
            if rec['company_signed'] is not None:
                net_company = company_currency.round(rec['company_signed'])
            else:
                net_company = company_currency.round(
                    net_tx * rate_map.get(currency.id if currency else 0, 1.0)
                )
            debit = net_company if net_company > 0 else 0.0
            credit = -net_company if net_company < 0 else 0.0
            running = company_currency.round(running + net_company)
            if currency and currency.id != company_currency.id and net_tx:
                amt_cur_classes = 'text'
                if net_tx < 0:
                    amt_cur_classes += ' text-danger'
                amt_cur_col = {
                    'name': currency.format(net_tx),
                    'no_format': net_tx,
                    'class': amt_cur_classes,
                }
            else:
                amt_cur_col = {'name': '', 'class': 'text'}
            date_col = {
                'name': fields.Date.to_string(rec['date']) if rec['date'] else '',
                'class': 'date',
            }
            lines.append({
                'id': report._get_generic_line_id(
                    rec['record_model'], rec['record_id'],
                    parent_line_id=line_dict_id,
                ),
                'name': self._format_child_label(rec, is_combined),
                'level': 3,
                'parent_id': line_dict_id,
                'caret_options': rec['record_model'],
                'columns': [
                    date_col,
                    {'name': rec['communication'] or '', 'class': 'text'},
                    {'name': rec['partner_name'] or '', 'class': 'text'},
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
        """Compact label for a drill-down row.

        ``[MGT]`` / ``[FAAP]`` source tag is prepended in COMBINED
        scope so the user can tell which side a line came from.
        Otherwise just the move name (Date, Communication, Partner
        already have their own columns).
        """
        parts = []
        if is_combined:
            parts.append('[%s]' % rec['src_tag'].upper())
        if rec['display_name']:
            parts.append(rec['display_name'])
        return ' · '.join(p for p in parts if p)

    # ---- per-source readers --------------------------------------------

    def _query_account_period(self, options, date_from, date_to,
                              include_drafts, rate_map, model_name):
        """Generator: yields ``(account_id, debit_inc, credit_inc)`` in
        company currency for one source model.

        17.0.10.0.0 — all source models expose ``debit`` / ``credit``
        in company currency; ``rate_map`` is preserved for back-compat
        but not used.

        17.0.9.0.1 (bugfix) — ``jito.ledger.statutory.view.account_id``
        is the **stock account.account.id**, not the FAAP mirror's
        ``jito.ledger.account.id``. Grouping by it would put the LL
        leg under a different account-id namespace from the NL leg,
        making them invisible to the combined GL. Group by
        ``faap_account_id`` (M2O → jito.ledger.account) instead, so
        LL and NL contributions merge under the same FAAP mirror row.
        Rows where ``faap_account_id`` is NULL (LL accounts with no
        mirror yet) are dropped — they wouldn't render in the NL
        chart anyway.
        """
        domain = self._build_domain(
            options, date_from, date_to,
            model_name=model_name, include_drafts=include_drafts,
        )
        partner_filter = options.get('partner_ids') or []
        partner_filter = [pid for pid in partner_filter if isinstance(pid, int)]
        if partner_filter:
            domain.append(('partner_id', 'in', partner_filter))
        if model_name == 'jito.ledger.statutory.view':
            group_field = 'faap_account_id'
            domain.append((group_field, '!=', False))
        else:
            group_field = 'account_id'
        Line = self.env[model_name]
        groups = Line.read_group(
            domain=domain,
            fields=[group_field, 'debit:sum', 'credit:sum'],
            groupby=[group_field],
            lazy=False,
        )
        for grp in groups:
            aid = grp.get(group_field) and grp[group_field][0]
            if not aid:
                continue
            yield aid, grp.get('debit') or 0.0, grp.get('credit') or 0.0

    def _compute_initial_balances(self, options, date_from, account_ids,
                                  include_drafts, rate_map, sources):
        """Sum each account's signed company-currency amount for moves
        dated *before* the period, across all selected source models.
        Returns ``{account_id: signed_balance}`` (positive = debit-side).

        17.0.10.0.0 — reads ``debit`` / ``credit`` directly from each
        source model; no rate_map translation needed.
        """
        out = defaultdict(float)
        if not account_ids:
            return out
        partner_filter = options.get('partner_ids') or []
        partner_filter = [pid for pid in partner_filter if isinstance(pid, int)]
        for _src_tag, model_name in sources:
            Line = self.env[model_name]
            domain = self._initial_domain(model_name, date_from, include_drafts, account_ids)
            if partner_filter:
                domain.append(('partner_id', 'in', partner_filter))
            # 17.0.9.0.1 — same statutory-view fix as
            # ``_query_account_period``: group by faap_account_id so
            # LL contributions merge with NL under the same FAAP
            # mirror id.
            if model_name == 'jito.ledger.statutory.view':
                group_field = 'faap_account_id'
            else:
                group_field = 'account_id'
            groups = Line.read_group(
                domain=domain,
                fields=[group_field, 'debit:sum', 'credit:sum'],
                groupby=[group_field],
                lazy=False,
            )
            for grp in groups:
                aid = grp.get(group_field) and grp[group_field][0]
                if not aid:
                    continue
                out[aid] += (grp.get('debit') or 0.0) - (grp.get('credit') or 0.0)
        return out

    def _initial_domain(self, model_name, date_from, include_drafts, account_ids):
        """Pre-period domain shape for a given source model. Mirrors
        ``_build_domain`` but with ``date < date_from`` and an
        account filter.

        17.0.9.0.1 — for ``jito.ledger.statutory.view``, the filter
        is on ``faap_account_id`` (M2O → jito.ledger.account), not
        ``account_id`` (M2O → account.account), because the caller
        passes jito.ledger.account ids.
        """
        date_str = fields.Date.to_string(date_from)
        company_clause = ('company_id', 'in', self.env.companies.ids)
        common_no_account = [
            ('date', '<', date_str),
            company_clause,
        ]
        if model_name == 'jito.ledger.move.line':
            domain = [('move_id.is_voided', '=', False)] + common_no_account
            domain.append(('account_id', 'in', account_ids))
            if not include_drafts:
                domain.insert(0, ('move_state', '=', 'posted'))
            return domain
        if model_name == 'jito.ledger.statutory.view':
            return [
                ('state', '=', 'posted'),
                ('faap_account_id', 'in', account_ids),
            ] + common_no_account
        if model_name == 'account.move.line':
            domain = list(common_no_account)
            domain.append(('account_id', 'in', account_ids))
            if not include_drafts:
                domain.insert(0, ('parent_state', '=', 'posted'))
            return domain
        raise ValueError("Unsupported source model: %r" % (model_name,))

    def _fetch_account_lines(self, options, date_from, date_to,
                             include_drafts, model_name, account_id, src_tag):
        """Return a list of dicts for the journal items under
        ``account_id`` (in the period) from one source model, normalised
        across NL / LL views.

        Keys: date, currency_id, amount_currency, company_signed,
        communication, partner_name, display_name, record_model,
        record_id, src_tag.

        ``company_signed`` is the signed amount **already in company
        currency** (positive = debit). When non-None, the expand
        callback uses it directly and skips the rate_map. LL sources
        always populate it from ``debit - credit``; NL leaves it None
        so the rate_map translation kicks in.
        """
        # 17.0.9.0.1 — statutory.view's ``account_id`` is the stock
        # account.account id, not the FAAP mirror. The caller passes
        # a jito.ledger.account id (matched from the parent row); for
        # the statutory.view source we filter on ``faap_account_id``.
        if model_name == 'jito.ledger.statutory.view':
            account_filter = [('faap_account_id', '=', account_id)]
        else:
            account_filter = [('account_id', '=', account_id)]
        domain = self._build_domain(
            options, date_from, date_to,
            model_name=model_name, include_drafts=include_drafts,
        ) + account_filter
        partner_filter = options.get('partner_ids') or []
        partner_filter = [pid for pid in partner_filter if isinstance(pid, int)]
        if partner_filter:
            domain.append(('partner_id', 'in', partner_filter))
        Line = self.env[model_name]
        records = Line.search(domain, order='date, id')
        out = []
        if model_name == 'jito.ledger.move.line':
            for r in records:
                out.append({
                    'date': r.date,
                    'currency_id': r.currency_id,
                    'amount_currency': r.amount_currency or 0.0,
                    'company_signed': (r.debit or 0.0) - (r.credit or 0.0),
                    'communication': r.move_ref or r.name or '',
                    'partner_name': r.partner_id.display_name if r.partner_id else '',
                    'display_name': r.move_name or '',
                    'record_model': 'jito.ledger.move.line',
                    'record_id': r.id,
                    'src_tag': src_tag,
                })
        elif model_name == 'jito.ledger.statutory.view':
            company_cur = self.env.company.currency_id
            for r in records:
                out.append({
                    'date': r.date,
                    'currency_id': r.currency_id or company_cur,
                    'amount_currency': r.amount_currency or 0.0,
                    'company_signed': (r.debit or 0.0) - (r.credit or 0.0),
                    'communication': (r.move_id.ref or '') if r.move_id else (r.name or ''),
                    'partner_name': r.partner_id.display_name if r.partner_id else '',
                    'display_name': (r.move_id.name or r.name or '') if r.move_id else (r.name or ''),
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
                    'communication': r.move_id.ref or r.name or '',
                    'partner_name': r.partner_id.display_name if r.partner_id else '',
                    'display_name': r.move_id.name or r.name or '',
                    'record_model': 'account.move.line',
                    'record_id': r.id,
                    'src_tag': src_tag,
                })
        return out

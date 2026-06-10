# -*- coding: utf-8 -*-

from collections import defaultdict

from odoo import fields, models, _
from odoo.exceptions import UserError


SCOPE_MANAGEMENT = 'management'
SCOPE_COMBINED = 'combined'

# 17.0.8.0.0 — per-scope source registry, structurally identical to
# general_ledger_handler.SCOPE_SOURCES. Default scope on the menu
# action is ``combined`` because the category feature exists to roll
# up FAAP + NL versions of the same business concept; the Management-
# only view is a degenerate case of that.
SCOPE_SOURCES = {
    SCOPE_MANAGEMENT: [('mgmt', 'jito.ledger.move.line')],
    SCOPE_COMBINED: [
        ('mgmt', 'jito.ledger.move.line'),
        ('faap', 'jito.ledger.statutory.view'),
    ],
}


class JitoCategorizedReportCustomHandler(models.AbstractModel):
    """Custom handler for the All Categories report (17.0.8.0.0).

    Rows are ``jito.ledger.account.category`` records (not accounts).
    Each parent row shows the category's summed Debit / Credit /
    Balance in company currency. Drill-down on a category emits one
    child row per constituent ``jito.ledger.account`` with its own
    period totals.

    Per-source totals are computed identically to the General Ledger
    handler — the only difference is the bucketing key (category
    instead of account) for the parent rows.
    """

    _name = 'jito.ledger.categorized.report.handler'
    _inherit = ['account.report.custom.handler', 'jito.ledger.report.handler.base']
    _description = 'Management Categorized Report Custom Handler'

    EXPAND_FUNC = '_report_expand_unfoldable_line_jito_categorized'

    # ---- caret options --------------------------------------------------

    def _caret_options_initializer(self):
        """Per-line caret-dropdown actions.

        Stock account_reports auto-appends "Annotate" when any caret
        options exist on a line, so we only declare the explicit
        choices here.

        * ``jito.ledger.account.category`` (category parent rows):
          **Open** (opens the category form).
        * ``jito.ledger.account`` (child rows): **Open**.
        """
        view_je = {
            'name': _("View Journal Entry"),
            'action': 'caret_option_open_record_form',
            'action_param': 'move_id',
        }
        return {
            'jito.ledger.account.category': [
                {'name': _("Open"), 'action': 'caret_option_open_record_form'},
            ],
            'jito.ledger.account': [
                {'name': _("Open"), 'action': 'caret_option_open_record_form'},
            ],
            # 17.0.9.1.0 — per-line drill-down rows carry their record
            # model as caret_options; surface "View Journal Entry"
            # on each so users can hop to the underlying move.
            'jito.ledger.move.line': [view_je],
            'jito.ledger.statutory.view': [view_je],
            'account.move.line': [view_je],
        }

    # ---- options --------------------------------------------------------

    def _custom_options_initializer(self, report, options, previous_options=None):
        """Seed options:

          * ``jito_rate_policy`` — FR-23 FX policy.
          * ``jito_data_scope`` — resolved from action context
            (``default_jito_data_scope``) → previous_options →
            ``combined`` default.
        """
        super()._custom_options_initializer(report, options, previous_options=previous_options)
        prev = previous_options or {}
        options['jito_rate_policy'] = (
            prev.get('jito_rate_policy') or 'period_end'
        )
        scope = (
            self.env.context.get('default_jito_data_scope')
            or prev.get('jito_data_scope')
            or SCOPE_COMBINED
        )
        if scope not in SCOPE_SOURCES:
            scope = SCOPE_COMBINED
        options['jito_data_scope'] = scope

    # ---- main report generation -----------------------------------------

    def _dynamic_lines_generator(self, report, options, all_column_groups_expression_totals, warnings=None):
        """Build one unfoldable parent row per active category. All
        active categories appear — including those with zero in-period
        activity — so the report always shows the user's full
        categorization taxonomy. "(Uncategorized)" trails at the
        bottom only when uncategorized accounts have actual activity.
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
                    options, date_from, date_to, include_drafts, rate_map, model_name):
                per_account_period[account_id]['debit'] += debit_inc
                per_account_period[account_id]['credit'] += credit_inc

        Category = self.env['jito.ledger.account.category']
        Account = self.env['jito.ledger.account']
        active_categories = Category.search([])

        # Look up category for every account that had activity so we
        # know which accounts go into uncategorized.
        accounts_with_activity = Account.browse(list(per_account_period.keys()))
        accts_by_cat = defaultdict(lambda: Account.browse())
        for acc in accounts_with_activity:
            accts_by_cat[acc.category_id.id] += acc

        # 17.0.9.1.1 — pre-period balance per account, so parent rows
        # show period-end Balance = initial + period_debit - period_credit
        # (matching GL semantics) and the drill-down can emit an
        # "Initial Balance" row + running totals.
        per_account_initial = self._compute_initial_balances(
            options, date_from, accounts_with_activity.ids,
            include_drafts, sources,
        )

        lines = []
        total_debit = total_credit = 0.0

        # 17.0.9.2.0 — column rework:
        #   Move = row's name (leftmost label slot)
        #   Columns = Label / Partner / Journal / Date / Account
        #             + Debit / Credit / Balance
        # Parent rows leave the 5 metadata cells blank.
        empty_meta = [
            {'name': '', 'class': 'text'},   # Label
            {'name': '', 'class': 'text'},   # Partner
            {'name': '', 'class': 'text'},   # Journal
            {'name': '', 'class': 'date'},   # Date
            {'name': '', 'class': 'text'},   # Account
        ]
        for cat in active_categories:
            cat_accounts = accts_by_cat.get(cat.id, Account.browse())
            cat_debit = sum(per_account_period[a.id]['debit'] for a in cat_accounts)
            cat_credit = sum(per_account_period[a.id]['credit'] for a in cat_accounts)
            cat_initial = sum(per_account_initial.get(a.id, 0.0) for a in cat_accounts)
            cat_debit_r = company_currency.round(cat_debit)
            cat_credit_r = company_currency.round(cat_credit)
            # Period-end balance = initial + period delta (running
            # balance semantics, matches General Ledger parent rows).
            cat_balance = company_currency.round(cat_initial + cat_debit - cat_credit)
            total_debit += cat_debit
            total_credit += cat_credit
            lines.append((0, {
                'id': report._get_generic_line_id(
                    'jito.ledger.account.category', cat.id,
                ),
                'name': cat.name,
                'level': 2,
                'unfoldable': True,
                'unfolded': bool(options.get('unfold_all')),
                'expand_function': self.EXPAND_FUNC,
                'columns': [
                    *empty_meta,
                    self._make_money_column(company_currency, cat_debit_r),
                    self._make_money_column(company_currency, cat_credit_r),
                    self._make_money_column(company_currency, cat_balance),
                ],
                'caret_options': 'jito.ledger.account.category',
            }))

        # 17.0.9.2.0 — uncategorized bucket dropped. Accounts without
        # a category are excluded from the report. (Was previously
        # rendered as a trailing "(Uncategorized)" row.)

        lines.append((0, {
            'id': report._get_generic_line_id(False, False, markup='total'),
            'name': _('Total'),
            'level': 1,
            'class': 'total',
            'columns': [
                *empty_meta,
                self._make_money_column(company_currency, company_currency.round(total_debit)),
                self._make_money_column(company_currency, company_currency.round(total_credit)),
                self._make_money_column(company_currency, company_currency.round(total_debit - total_credit)),
            ],
        }))

        return lines

    # ---- expand callback ------------------------------------------------

    def _report_expand_unfoldable_line_jito_categorized(
            self, line_dict_id, groupby, options, progress, offset,
            unfold_all_batch_data=None):
        """Drill-down: emit one row per **journal item** under the
        clicked category, sorted by date ASC (17.0.9.1.0). Each row
        shows Date / Account / Move (entry id) + Debit / Credit /
        Balance in company currency. Items are NOT grouped by account
        — every line on every account in the category appears in
        chronological order.
        """
        report = self.env['account.report'].browse(options.get('report_id'))
        if not report:
            report = self.env.ref(
                'jito_ledger_reports.management_categorized_report',
                raise_if_not_found=False,
            )
        if not report:
            raise UserError(_(
                "Categorized report record not found. Re-upgrade the "
                "jito_ledger_reports module."
            ))

        markup, model, res_id = report._parse_line_id(line_dict_id)[-1]
        if model != 'jito.ledger.account.category':
            raise UserError(_(
                "Wrong ID for Categorized line to expand: %s",
                line_dict_id,
            ))
        is_uncategorized = (markup == 'uncategorized')

        company = self.env.company
        company_currency = company.currency_id
        date_from, date_to = self._resolve_date_range(options)
        include_drafts = bool(options.get('show_draft') or options.get('all_entries'))
        sources = SCOPE_SOURCES[options['jito_data_scope']]

        # Resolve which jito.ledger.account ids belong to the
        # clicked category bucket. Categorized accounts come straight
        # from the M2O; the "(Uncategorized)" bucket is everything
        # else for the active company.
        Account = self.env['jito.ledger.account']
        if is_uncategorized:
            target_accounts = Account.search([
                ('category_id', '=', False),
                ('company_id', 'in', self.env.companies.ids),
            ])
        else:
            category = self.env['jito.ledger.account.category'].browse(res_id)
            target_accounts = category.account_ids.filtered(
                lambda a: a.company_id in self.env.companies
            )
        if not target_accounts:
            return {'lines': [], 'offset_increment': 0, 'has_more': False, 'progress': {}}

        # 17.0.9.1.1 — running balance: start at the category's
        # initial (sum of constituent accounts' pre-period balances)
        # and accumulate per line in date order.
        per_account_initial = self._compute_initial_balances(
            options, date_from, target_accounts.ids,
            include_drafts, sources,
        )
        category_initial = sum(
            per_account_initial.get(a.id, 0.0) for a in target_accounts
        )
        running = company_currency.round(category_initial)

        # Fetch raw line records across all selected sources, merge,
        # sort chronologically (ties broken by record id).
        records = []
        for src_tag, model_name in sources:
            records.extend(self._fetch_category_lines(
                options, date_from, date_to, include_drafts,
                model_name, target_accounts.ids, src_tag,
            ))
        records.sort(key=lambda r: (r['date'] or date_from, r['record_id']))

        lines = []
        # Initial Balance row — anchors the running balance the user
        # sees on subsequent rows.
        if not offset:
            lines.append({
                'id': report._get_generic_line_id(
                    'jito.ledger.account.category',
                    res_id if not is_uncategorized else 0,
                    markup='initial', parent_line_id=line_dict_id,
                ),
                'name': _('Initial Balance'),
                'level': 3,
                'parent_id': line_dict_id,
                'class': 'o_account_reports_initial_balance',
                'columns': [
                    {'name': '', 'class': 'text'},   # Label
                    {'name': '', 'class': 'text'},   # Partner
                    {'name': '', 'class': 'text'},   # Journal
                    {'name': '', 'class': 'date'},   # Date
                    {'name': '', 'class': 'text'},   # Account
                    self._make_money_column(company_currency, 0.0),
                    self._make_money_column(company_currency, 0.0),
                    self._make_money_column(company_currency, running),
                ],
            })

        for rec in records:
            debit = company_currency.round(rec['debit'] or 0.0)
            credit = company_currency.round(rec['credit'] or 0.0)
            # Accumulate: running += debit - credit (signed delta).
            running = company_currency.round(running + debit - credit)
            date_col = {
                'name': fields.Date.to_string(rec['date']) if rec['date'] else '',
                'class': 'date',
            }
            # 17.0.9.2.0 — Move name lives in the row's left-most
            # label (``name``); explicit columns are
            # Label / Partner / Journal / Date / Account.
            lines.append({
                'id': report._get_generic_line_id(
                    rec['record_model'], rec['record_id'],
                    parent_line_id=line_dict_id,
                ),
                'name': rec['move_label'] or '',
                'level': 3,
                'parent_id': line_dict_id,
                'caret_options': rec['record_model'],
                'columns': [
                    {'name': rec['line_label'] or '', 'class': 'text'},
                    {'name': rec['partner_label'] or '', 'class': 'text'},
                    {'name': rec['journal_label'] or '', 'class': 'text'},
                    date_col,
                    {'name': rec['account_label'] or '', 'class': 'text'},
                    self._make_money_column(company_currency, debit),
                    self._make_money_column(company_currency, credit),
                    self._make_money_column(company_currency, running),
                ],
            })

        return {
            'lines': lines,
            'offset_increment': len(lines),
            'has_more': False,
            'progress': {},
        }

    def _fetch_category_lines(self, options, date_from, date_to,
                              include_drafts, model_name, account_ids,
                              src_tag):
        """Return per-line dicts for a category's accounts under one
        source model. Used by the per-line drill-down (17.0.9.1.0).

        Keys per dict: date, debit, credit, account_label, move_label,
        line_label, record_model, record_id, src_tag.

        For ``jito.ledger.statutory.view``, the filter is on
        ``faap_account_id`` (the FAAP mirror, per the 17.0.9.0.1 bug
        fix); for the NL source it's on ``account_id`` directly.
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
            domain.append(('faap_account_id', 'in', account_ids))
        else:
            domain.append(('account_id', 'in', account_ids))
        Line = self.env[model_name]
        records = Line.search(domain, order='date, id')
        out = []
        if model_name == 'jito.ledger.move.line':
            for r in records:
                account = r.account_id
                journal = r.journal_id
                out.append({
                    'date': r.date,
                    'debit': r.debit or 0.0,
                    'credit': r.credit or 0.0,
                    'account_label': '%s %s' % (
                        account.code or '', account.name or '',
                    ),
                    'move_label': r.move_name or r.move_id.name or '',
                    'line_label': r.name or '',
                    'partner_label': (
                        r.partner_id.display_name if r.partner_id else ''
                    ),
                    'journal_label': (
                        journal.code or journal.name or ''
                    ) if journal else '',
                    'record_model': 'jito.ledger.move.line',
                    'record_id': r.id,
                    'src_tag': src_tag,
                })
        elif model_name == 'jito.ledger.statutory.view':
            for r in records:
                # ``account_id`` on the statutory view is the stock
                # account; ``faap_account_id`` is the FAAP mirror.
                # Prefer the mirror's [code name] for consistency
                # with the NL source label.
                mirror = r.faap_account_id
                account_label = (
                    '%s %s' % (mirror.code or '', mirror.name or '')
                    if mirror else
                    '%s %s' % (
                        r.account_id.code or '', r.account_id.name or ''
                    )
                )
                journal = r.journal_id
                out.append({
                    'date': r.date,
                    'debit': r.debit or 0.0,
                    'credit': r.credit or 0.0,
                    'account_label': account_label,
                    'move_label': (r.move_id.name if r.move_id else '') or '',
                    'line_label': r.name or '',
                    'partner_label': (
                        r.partner_id.display_name if r.partner_id else ''
                    ),
                    'journal_label': (
                        journal.code or journal.name or ''
                    ) if journal else '',
                    'record_model': 'jito.ledger.statutory.view',
                    'record_id': r.id,
                    'src_tag': src_tag,
                })
        elif model_name == 'account.move.line':
            for r in records:
                journal = r.journal_id
                out.append({
                    'date': r.date,
                    'debit': r.debit or 0.0,
                    'credit': r.credit or 0.0,
                    'account_label': '%s %s' % (
                        r.account_id.code or '', r.account_id.name or '',
                    ),
                    'move_label': r.move_id.name or '',
                    'line_label': r.name or '',
                    'partner_label': (
                        r.partner_id.display_name if r.partner_id else ''
                    ),
                    'journal_label': (
                        journal.code or journal.name or ''
                    ) if journal else '',
                    'record_model': 'account.move.line',
                    'record_id': r.id,
                    'src_tag': src_tag,
                })
        return out

    # ---- queries --------------------------------------------------------

    def _compute_initial_balances(self, options, date_from, account_ids,
                                  include_drafts, sources):
        """Sum each account's signed company-currency balance for moves
        dated *before* the period, across all selected source models.
        Returns ``{account_id: signed_balance}`` (positive = debit-side).

        17.0.9.1.1 — mirrors the GL handler's helper of the same name;
        used by the Categorized parent rows + drill-down to render
        period-end + running balances. Statutory-view rows filter on
        ``faap_account_id`` (per the 17.0.9.0.1 bug fix).
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
        """Pre-period domain shape for a given source model — local
        copy of ``general_ledger_handler._initial_domain`` (17.0.9.1.1).
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

    def _query_account_period(self, options, date_from, date_to,
                              include_drafts, rate_map, model_name):
        """Yield ``(account_id, debit_inc, credit_inc)`` in company
        currency for one source model. Structurally identical to
        ``general_ledger_handler._query_account_period``.

        17.0.10.0.0 — reads ``debit`` / ``credit`` directly across all
        source models; ``rate_map`` is preserved for back-compat but
        no longer used.
        """
        domain = self._build_domain(
            options, date_from, date_to,
            model_name=model_name, include_drafts=include_drafts,
        )
        partner_filter = options.get('partner_ids') or []
        partner_filter = [pid for pid in partner_filter if isinstance(pid, int)]
        if partner_filter:
            domain.append(('partner_id', 'in', partner_filter))
        # 17.0.9.0.1 — statutory.view's ``account_id`` is the stock
        # account.account id, not the FAAP mirror. Group on
        # ``faap_account_id`` so LL contributions merge with NL
        # under the same jito.ledger.account row.
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

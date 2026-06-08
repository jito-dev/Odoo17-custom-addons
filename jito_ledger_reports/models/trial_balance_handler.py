# -*- coding: utf-8 -*-

from collections import defaultdict

from odoo import api, fields, models, _


class JitoTrialBalanceCustomHandler(models.AbstractModel):
    """Custom handler for the Management Trial Balance report.

    Pattern per stock Odoo's
    odoo17_enterprise/odoo/addons/account_reports/models/account_general_ledger.py:14-85.
    Inherits ``account.report.custom.handler`` (Enterprise) and
    implements two hooks:

      * ``_custom_options_initializer`` — augments the report options
        with a ``rate_policy`` selection (period_end / spot_today)
        per HLD Decision #1, parent FR-23.

      * ``_dynamic_lines_generator`` — queries ``jito.ledger.move.line``,
        aggregates by ``jito.ledger.account``, applies FX presentation
        translation at report time, and returns ``(sequence, line_dict)``
        tuples for the report's tree.

    v1 ignores account_reports' ``column_groups`` (comparison periods)
    for simplicity — single column group only. Multi-period comparison
    is a v1.x improvement.
    """

    _name = 'jito.ledger.trial.balance.report.handler'
    _inherit = ['account.report.custom.handler', 'jito.ledger.report.handler.base']
    _description = 'Management Trial Balance Custom Handler'

    # ---- options --------------------------------------------------------

    def _custom_options_initializer(self, report, options, previous_options=None):
        """Seed options for the Trial Balance.

          * ``jito_rate_policy`` — FR-23 / Decision #1 FX policy.
          * ``jito_tb_mode`` (17.0.9.4.0) — render mode:
              - ``categorized`` (default): per-category header +
                accounts inside + subtotal + grand total.
              - ``flat``: one row per account sorted by code; no
                category grouping. Used by the Non-Leading Ledger
                → Trial Balance menu.
              - ``category_summary``: one row per category showing
                summed Debit/Credit/Balance, no account rows. Used by
                Categorized → Trial Balance.

            Resolution order for mode: action context
            (``default_jito_tb_mode``) → previous_options →
            ``categorized``.
        """
        super()._custom_options_initializer(report, options, previous_options=previous_options)
        prev = previous_options or {}
        options['jito_rate_policy'] = prev.get('jito_rate_policy') or 'period_end'
        mode = (
            self.env.context.get('default_jito_tb_mode')
            or prev.get('jito_tb_mode')
            or 'categorized'
        )
        if mode not in ('categorized', 'flat', 'category_summary'):
            mode = 'categorized'
        options['jito_tb_mode'] = mode

        # 17.0.9.5.1 — Trial Balance renders the same Debit/Credit
        # base columns under three logical groups: "Initial Balance"
        # / <period label> / "End Balance". We rewrite
        # ``options['column_headers']`` to declare three header
        # entries, then re-invoke ``report._init_options_columns``
        # so the framework rebuilds ``options['columns']`` (6 cells,
        # group-major) and ``options['column_groups']`` (3 entries)
        # against the new headers. Each header carries a unique
        # ``forced_options['jito_tb_bucket']`` value so its
        # hashable_key — and therefore the resulting
        # ``column_group_key`` — differs per bucket; otherwise all
        # three would collapse to a single group_key. The handler's
        # ``_tb_columns`` already emits the 6 cells in the matching
        # group-major order (Initial.Debit, Initial.Credit,
        # Period.Debit, Period.Credit, End.Debit, End.Credit), so no
        # change is needed on the lines side.
        #
        # Pattern: stock account.report's comparison feature uses the
        # same ``column_headers`` mechanism for date-period grouping
        # (``odoo17_enterprise/.../account_report.py:1322``); we
        # repurpose it for logical (non-date) buckets.
        period_label = (options.get('date') or {}).get('string') or _('Period')
        options['column_headers'] = [
            [
                {
                    'name': _('Initial Balance'),
                    'forced_options': {'jito_tb_bucket': 'initial'},
                },
                {
                    'name': period_label,
                    'forced_options': {'jito_tb_bucket': 'period'},
                },
                {
                    'name': _('End Balance'),
                    'forced_options': {'jito_tb_bucket': 'end'},
                },
            ],
        ]
        report._init_options_columns(options, previous_options=previous_options)

    # ---- main report generation -----------------------------------------

    def _dynamic_lines_generator(self, report, options, all_column_groups_expression_totals, warnings=None):
        """Build the trial-balance lines.

        For each `jito.ledger.account` with activity in the date range:
          * Sum debit-side and credit-side `amount_currency` per
            transaction currency.
          * Translate to company currency at the rate determined by
            the rate_policy option.
          * Round per company currency precision.
          * Emit one report line with debit, credit, balance columns.

        At the bottom, emit a single Total line.

        Source filter: posted, non-voided `jito.ledger.move` only.
        """
        company = self.env.company
        company_currency = company.currency_id

        date_from, date_to = self._resolve_date_range(options)

        # 17.0.10.0.0 — ``debit`` / ``credit`` are now stored on the
        # line (frozen at posting time per the company-currency ADR).
        # Sum them directly; no more report-time FX translation via
        # rate_map. ``jito_rate_policy`` is preserved on the options
        # dict for filter back-compat but is no-op here.
        Line = self.env['jito.ledger.move.line']
        domain = self._build_domain(options, date_from, date_to)
        groups = Line.read_group(
            domain=domain,
            fields=['account_id', 'debit:sum', 'credit:sum'],
            groupby=['account_id'],
            lazy=False,
        )

        per_account_totals = defaultdict(lambda: {'debit': 0.0, 'credit': 0.0})
        for grp in groups:
            account_id = grp.get('account_id') and grp['account_id'][0]
            if not account_id:
                continue
            per_account_totals[account_id]['debit'] = grp.get('debit') or 0.0
            per_account_totals[account_id]['credit'] = grp.get('credit') or 0.0

        Account = self.env['jito.ledger.account']
        accounts = Account.browse(list(per_account_totals.keys()))

        # 17.0.9.5.0 — pre-period balances per account, so the
        # report can show Initial Debit / Initial Credit AND
        # End Debit / End Credit alongside period Debit / Credit.
        per_account_initial = self._compute_initial_balances_for_tb(
            options, date_from, accounts.ids,
        )

        mode = options.get('jito_tb_mode', 'categorized')
        if mode == 'flat':
            return self._render_flat(
                report, company_currency, accounts,
                per_account_totals, per_account_initial,
            )
        if mode == 'category_summary':
            return self._render_category_summary(
                report, company_currency, accounts,
                per_account_totals, per_account_initial,
            )
        # Default — categorized layout (existing behavior).
        return self._render_categorized(
            report, company_currency, accounts,
            per_account_totals, per_account_initial,
        )

    def _compute_initial_balances_for_tb(self, options, date_from, account_ids):
        """Sum each account's signed company-currency balance for
        moves dated *before* ``date_from``. Returns
        ``{account_id: signed_balance}`` (positive = debit-side).
        Same shape as the GL handler's helper but local to TB; only
        the NL source is considered (TB is management-ledger only).
        """
        out = defaultdict(float)
        if not account_ids:
            return out
        include_drafts = bool(
            options.get('show_draft') or options.get('all_entries')
        )
        date_str = fields.Date.to_string(date_from)
        domain = [
            ('move_id.is_voided', '=', False),
            ('date', '<', date_str),
            ('company_id', 'in', self.env.companies.ids),
            ('account_id', 'in', account_ids),
        ]
        if not include_drafts:
            domain.insert(0, ('move_state', '=', 'posted'))
        Line = self.env['jito.ledger.move.line']
        groups = Line.read_group(
            domain=domain,
            fields=['account_id', 'debit:sum', 'credit:sum'],
            groupby=['account_id'],
            lazy=False,
        )
        for grp in groups:
            aid = grp.get('account_id') and grp['account_id'][0]
            if not aid:
                continue
            out[aid] = (grp.get('debit') or 0.0) - (grp.get('credit') or 0.0)
        return out

    def _tb_columns(self, company_currency, initial, debit, credit):
        """Return the 6-cell ``columns`` list for one Trial Balance
        row (account or category), given the account's signed
        ``initial`` balance and its period ``debit`` / ``credit``
        company-currency totals. Splits signed initial + end values
        into the canonical debit/credit columns.
        """
        end = initial + debit - credit
        initial_debit = max(initial, 0.0)
        initial_credit = max(-initial, 0.0)
        end_debit = max(end, 0.0)
        end_credit = max(-end, 0.0)
        return [
            self._make_money_column(company_currency, company_currency.round(initial_debit)),
            self._make_money_column(company_currency, company_currency.round(initial_credit)),
            self._make_money_column(company_currency, company_currency.round(debit)),
            self._make_money_column(company_currency, company_currency.round(credit)),
            self._make_money_column(company_currency, company_currency.round(end_debit)),
            self._make_money_column(company_currency, company_currency.round(end_credit)),
        ]

    def _tb_empty_columns(self):
        return [{'name': '', 'class': 'number'} for _ in range(6)]

    # ---- render modes ---------------------------------------------------

    def _render_categorized(self, report, company_currency, accounts,
                            per_account_totals, per_account_initial):
        """Categorized layout: per-category header → account rows →
        category subtotal → grand total. Updated 17.0.9.5.0 to emit
        6-column Initial/Period/End layout (signed balance split
        into debit/credit pairs).

        17.0.9.5.2 — uncategorized accounts are skipped (same as
        ``_render_category_summary``); the Total row excludes them.
        """
        buckets = self._bucket_accounts_by_category(accounts)
        lines = []
        total_initial = 0.0
        total_debit = 0.0
        total_credit = 0.0
        for bucket in buckets:
            cat = bucket['category']
            if not cat:
                continue
            cat_name = cat.name
            cat_initial = 0.0
            cat_debit = 0.0
            cat_credit = 0.0

            lines.append((0, {
                'id': report._get_generic_line_id(
                    'jito.ledger.account.category',
                    cat.id if cat else 0,
                    markup='category_header',
                ),
                'name': cat_name,
                'level': 1,
                'columns': self._tb_empty_columns(),
            }))

            for account in bucket['accounts']:
                tots = per_account_totals[account.id]
                initial = per_account_initial.get(account.id, 0.0)
                debit = tots['debit']
                credit = tots['credit']
                cat_initial += initial
                cat_debit += debit
                cat_credit += credit
                total_initial += initial
                total_debit += debit
                total_credit += credit
                lines.append((0, {
                    'id': report._get_generic_line_id('jito.ledger.account', account.id),
                    'name': '%s %s' % (account.code, account.name or ''),
                    'level': 2,
                    'caret_options': False,
                    'columns': self._tb_columns(
                        company_currency, initial, debit, credit,
                    ),
                }))

            lines.append((0, {
                'id': report._get_generic_line_id(
                    'jito.ledger.account.category',
                    cat.id if cat else 0,
                    markup='category_total',
                ),
                'name': _("Subtotal %s", cat_name),
                'level': 1,
                'class': 'total',
                'columns': self._tb_columns(
                    company_currency, cat_initial, cat_debit, cat_credit,
                ),
            }))

        lines.append((0, {
            'id': report._get_generic_line_id(False, False, markup='total'),
            'name': _('Total'),
            'level': 1,
            'class': 'total',
            'columns': self._tb_columns(
                company_currency, total_initial, total_debit, total_credit,
            ),
        }))
        return lines

    def _render_flat(self, report, company_currency, accounts,
                     per_account_totals, per_account_initial):
        """Flat per-account layout (no category grouping). Used by
        Non-Leading Ledger → Trial Balance.
        """
        lines = []
        total_initial = 0.0
        total_debit = total_credit = 0.0
        for account in accounts.sorted('code'):
            tots = per_account_totals.get(account.id, {})
            initial = per_account_initial.get(account.id, 0.0)
            debit = tots.get('debit', 0.0)
            credit = tots.get('credit', 0.0)
            total_initial += initial
            total_debit += debit
            total_credit += credit
            lines.append((0, {
                'id': report._get_generic_line_id('jito.ledger.account', account.id),
                'name': '%s %s' % (account.code or '', account.name or ''),
                'level': 2,
                'caret_options': False,
                'columns': self._tb_columns(
                    company_currency, initial, debit, credit,
                ),
            }))
        lines.append((0, {
            'id': report._get_generic_line_id(False, False, markup='total'),
            'name': _('Total'),
            'level': 1,
            'class': 'total',
            'columns': self._tb_columns(
                company_currency, total_initial, total_debit, total_credit,
            ),
        }))
        return lines

    def _render_category_summary(self, report, company_currency, accounts,
                                 per_account_totals, per_account_initial):
        """One row per category (sum across its accounts). No
        per-account rows. Used by Categorized → Trial Balance.

        17.0.9.5.2 — accounts with no ``category_id`` are dropped
        entirely (no "(Uncategorized)" row, and their values are
        excluded from the Total row). Configuration mismatch surfaces
        through the per-account General Ledger views instead.
        """
        buckets = self._bucket_accounts_by_category(accounts)
        lines = []
        total_initial = 0.0
        total_debit = total_credit = 0.0
        for bucket in buckets:
            cat = bucket['category']
            if not cat:
                continue
            cat_name = cat.name
            cat_initial = sum(
                per_account_initial.get(a.id, 0.0) for a in bucket['accounts']
            )
            cat_debit = sum(
                per_account_totals.get(a.id, {}).get('debit', 0.0)
                for a in bucket['accounts']
            )
            cat_credit = sum(
                per_account_totals.get(a.id, {}).get('credit', 0.0)
                for a in bucket['accounts']
            )
            total_initial += cat_initial
            total_debit += cat_debit
            total_credit += cat_credit
            lines.append((0, {
                'id': report._get_generic_line_id(
                    'jito.ledger.account.category',
                    cat.id if cat else 0,
                    markup='category_summary',
                ),
                'name': cat_name,
                'level': 2,
                'caret_options': (
                    'jito.ledger.account.category' if cat else False
                ),
                'columns': self._tb_columns(
                    company_currency, cat_initial, cat_debit, cat_credit,
                ),
            }))
        lines.append((0, {
            'id': report._get_generic_line_id(False, False, markup='total'),
            'name': _('Total'),
            'level': 1,
            'class': 'total',
            'columns': self._tb_columns(
                company_currency, total_initial, total_debit, total_credit,
            ),
        }))
        return lines

    # Shared helpers (_build_domain / _resolve_date_range /
    # _resolve_rate_date / _build_rate_map / _make_money_column /
    # _bucket_accounts_by_category) live on
    # jito.ledger.report.handler.base — inherited above.

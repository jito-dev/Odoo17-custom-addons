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
        """Add the rate_policy option to the report options dict.

        Per HLD Decision #1 + FR-23: user-selectable rate policy
        (Spot-today / Period-end). Period-end is the default — the
        rate at the last day of the report's date range.
        """
        super()._custom_options_initializer(report, options, previous_options=previous_options)
        # Carry forward the user's previous choice if any.
        prev = (previous_options or {}).get('jito_rate_policy')
        options['jito_rate_policy'] = prev or 'period_end'

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

        # Build the report lines — bucketed by category (17.0.7.0.0).
        # Inside each bucket, accounts stay sorted by code. Category
        # header + subtotal rows wrap each bucket; uncategorized
        # accounts fall into a trailing "(Uncategorized)" bucket.
        Account = self.env['jito.ledger.account']
        accounts = Account.browse(list(per_account_totals.keys()))
        buckets = self._bucket_accounts_by_category(accounts)

        lines = []
        total_debit = 0.0
        total_credit = 0.0
        for bucket in buckets:
            cat = bucket['category']
            cat_name = cat.name if cat else _("(Uncategorized)")
            cat_debit = 0.0
            cat_credit = 0.0

            # Category header row — blank columns; the row's job is to
            # label the section that follows. Level 1 keeps it
            # visually distinct from account rows (level 2).
            lines.append((0, {
                'id': report._get_generic_line_id(
                    'jito.ledger.account.category',
                    cat.id if cat else 0,
                    markup='category_header',
                ),
                'name': cat_name,
                'level': 1,
                'columns': [
                    {'name': '', 'class': 'number'},
                    {'name': '', 'class': 'number'},
                    {'name': '', 'class': 'number'},
                ],
            }))

            for account in bucket['accounts']:
                tots = per_account_totals[account.id]
                debit = company_currency.round(tots['debit'])
                credit = company_currency.round(tots['credit'])
                balance = debit - credit
                cat_debit += debit
                cat_credit += credit
                total_debit += debit
                total_credit += credit
                lines.append((0, {
                    'id': report._get_generic_line_id('jito.ledger.account', account.id),
                    'name': '%s %s' % (account.code, account.name or ''),
                    'level': 2,
                    'caret_options': False,
                    'columns': [
                        self._make_money_column(company_currency, debit),
                        self._make_money_column(company_currency, credit),
                        self._make_money_column(company_currency, balance),
                    ],
                }))

            cat_debit_r = company_currency.round(cat_debit)
            cat_credit_r = company_currency.round(cat_credit)
            cat_balance = company_currency.round(cat_debit - cat_credit)
            lines.append((0, {
                'id': report._get_generic_line_id(
                    'jito.ledger.account.category',
                    cat.id if cat else 0,
                    markup='category_total',
                ),
                'name': _("Subtotal %s", cat_name),
                'level': 1,
                'class': 'total',
                'columns': [
                    self._make_money_column(company_currency, cat_debit_r),
                    self._make_money_column(company_currency, cat_credit_r),
                    self._make_money_column(company_currency, cat_balance),
                ],
            }))

        # Grand Total line at the bottom.
        total_balance = company_currency.round(total_debit - total_credit)
        lines.append((0, {
            'id': report._get_generic_line_id(False, False, markup='total'),
            'name': _('Total'),
            'level': 1,
            'class': 'total',
            'columns': [
                self._make_money_column(company_currency, company_currency.round(total_debit)),
                self._make_money_column(company_currency, company_currency.round(total_credit)),
                self._make_money_column(company_currency, total_balance),
            ],
        }))

        return lines

    # Shared helpers (_build_domain / _resolve_date_range /
    # _resolve_rate_date / _build_rate_map / _make_money_column) live
    # on jito.ledger.report.handler.base — inherited above.

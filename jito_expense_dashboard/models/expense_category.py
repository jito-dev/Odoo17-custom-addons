# -*- coding: utf-8 -*-
from odoo import fields, models


class JitoExpenseCategory(models.Model):
    """Management categorisation of expense accounts.

    Odoo's own groupings are unusable for an executive view of spend:

    - ``account.root`` is an SQL view whose name is ``LEFT(code, 2)``. It can
      only ever render as ``60``, ``61`` ... and no record exists to rename.
    - ``account.group`` is optional and, in this database, is populated for
      5 of 31 expense accounts (a single group, "Software & Subscriptions").

    So the categorisation lives here, on records an accountant can edit, and is
    mirrored onto ``account.move.line`` as a stored field so pivots and charts
    can group by it.
    """
    _name = 'jito.expense.category'
    _description = 'Expense Category (management reporting)'
    _order = 'sequence, code'

    name = fields.Char(required=True, translate=True)
    code = fields.Char(
        required=True,
        help="Technical key, stable across renames. Used by the account "
             "auto-assignment rules and by the dashboard.",
    )
    sequence = fields.Integer(
        default=50,
        help="Drives the series order in the dashboard charts and tables.",
    )
    color = fields.Integer(string="Colour Index", default=0)
    active = fields.Boolean(default=True)
    note = fields.Char(
        string="Guidance",
        help="Shown to whoever maintains the chart of accounts: what belongs here.",
    )

    account_ids = fields.One2many(
        'account.account', 'expense_category_id', string="Accounts",
    )
    account_count = fields.Integer(compute='_compute_account_count')

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'The category code must be unique.'),
    ]

    def _compute_account_count(self):
        counts = dict(self.env['account.account']._read_group(
            [('expense_category_id', 'in', self.ids)],
            groupby=['expense_category_id'],
            aggregates=['__count'],
        ))
        for category in self:
            category.account_count = counts.get(category, 0)

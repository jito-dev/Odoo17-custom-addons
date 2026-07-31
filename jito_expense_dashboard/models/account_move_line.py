# -*- coding: utf-8 -*-
from odoo import fields, models


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    # Stored, therefore groupable. A non-stored related field would raise
    # "Cannot convert field account.move.line.expense_category_id to SQL" the
    # moment a pivot or chart tried to group by it - which is exactly why
    # account_type cannot be used as a dashboard dimension.
    expense_category_id = fields.Many2one(
        'jito.expense.category',
        string="Expense Category",
        related='account_id.expense_category_id',
        store=True,
        index=True,
        readonly=True,
    )

# -*- coding: utf-8 -*-

from odoo import fields, models


class AccountMoveRevolut(models.Model):
    _inherit = 'account.move'

    revolut_transaction_id = fields.Many2one(
        'revolut.transaction', string='Revolut Transaction',
        readonly=True, copy=False, ondelete='set null',
    )

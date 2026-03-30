# -*- coding: utf-8 -*-

from odoo import fields, models


class AccountBankStatementLine(models.Model):
    _inherit = 'account.bank.statement.line'

    upwork_tx_ref = fields.Char(
        string='Upwork TX Ref',
        readonly=True,
        index='trigram',
        copy=False,
    )


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    upwork_tx_ref = fields.Char(
        related='move_id.statement_line_id.upwork_tx_ref',
        string='Upwork TX Ref',
        store=True,
    )

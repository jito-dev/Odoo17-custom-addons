# -*- coding: utf-8 -*-

from odoo import fields, models


class AccountBankStatementLine(models.Model):
    _inherit = 'account.bank.statement.line'

    revolut_tx_ref = fields.Char(
        string='Revolut TX ID',
        readonly=True,
        index='trigram',
        copy=False,
    )


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    revolut_tx_ref = fields.Char(
        related='move_id.statement_line_id.revolut_tx_ref',
        string='Revolut TX ID',
        store=True,
    )

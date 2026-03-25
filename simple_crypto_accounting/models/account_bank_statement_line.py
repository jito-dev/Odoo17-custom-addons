# -*- coding: utf-8 -*-

from odoo import fields, models


class AccountBankStatementLine(models.Model):
    _inherit = 'account.bank.statement.line'

    crypto_tx_ref = fields.Char(
        string='Crypto TX Ref',
        readonly=True,
        index='trigram',
        copy=False,
    )


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    crypto_tx_ref = fields.Char(
        related='move_id.statement_line_id.crypto_tx_ref',
        string='Crypto TX Ref',
        store=True,
    )

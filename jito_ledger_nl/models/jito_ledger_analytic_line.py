# -*- coding: utf-8 -*-

"""ML Analytic Line (17.0.9.0.0).

Parallel to stock ``account.analytic.line`` — generated when a
``jito.ledger.move`` posts, one row per (line, analytic account,
percentage). Kept entirely separate from stock ``account.analytic.line``
so ML analytics never leak into stock analytic reporting.

Amounts are stored in the originating ML line's transaction currency
(``currency_id``), not company currency, because ML lines are
multi-currency (HLD Decision #8). Any cross-line rollup must convert via
``res.currency._convert``.
"""

from odoo import api, fields, models


class JitoLedgerAnalyticLine(models.Model):
    _name = 'jito.ledger.analytic.line'
    _description = 'ML Analytic Line'
    _order = 'date desc, id desc'

    name = fields.Char(string='Description', required=True)
    date = fields.Date(required=True, index=True, default=fields.Date.context_today)
    amount = fields.Monetary(
        string='Amount', required=True, default=0.0,
        currency_field='currency_id',
        help="Signed amount in the source ML line's transaction currency. "
             "Mirrors stock's convention: debit-side ML lines yield a "
             "negative analytic amount (cost), credit-side a positive one.",
    )
    account_id = fields.Many2one(
        'jito.ledger.analytic.account',
        string='Analytic Account', required=True, ondelete='restrict',
        index=True,
    )
    plan_id = fields.Many2one(
        'jito.ledger.analytic.plan',
        string='Plan', related='account_id.root_plan_id', store=True,
        index=True,
    )
    partner_id = fields.Many2one('res.partner', string='Partner')
    currency_id = fields.Many2one('res.currency', string='Currency')
    company_id = fields.Many2one('res.company', string='Company', required=True)

    move_id = fields.Many2one(
        'jito.ledger.move', string='Journal Entry',
        ondelete='cascade', index=True,
    )
    move_line_id = fields.Many2one(
        'jito.ledger.move.line', string='Journal Item',
        ondelete='cascade', index=True,
    )

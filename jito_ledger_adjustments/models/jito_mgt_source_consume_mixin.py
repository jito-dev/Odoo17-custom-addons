# -*- coding: utf-8 -*-

"""Shared per-source consume row for partial restatement/regrouping
(17.0.11.0.0).

A partial adjustment consumes only part of a source statutory line. Each
concrete sub-model (restatement / regrouping source line) adds its own
parent Many2one; the shared columns + logic live here.
"""

from odoo import api, fields, models


class JitoMgtSourceConsumeMixin(models.AbstractModel):
    _name = 'jito.mgt.source.consume.mixin'
    _description = 'Adjustment Source (partial consume) mixin'
    _order = 'id'

    move_line_id = fields.Many2one(
        'account.move.line', string='Statutory Source Line',
        required=True, ondelete='cascade',
    )
    currency_id = fields.Many2one(
        related='move_line_id.currency_id', readonly=True,
    )
    account_id = fields.Many2one(
        related='move_line_id.account_id', readonly=True,
    )
    source_amount_currency = fields.Monetary(
        string='Line Amount', related='move_line_id.amount_currency',
        currency_field='currency_id', readonly=True,
    )
    remaining_display = fields.Monetary(
        string='Remaining', compute='_compute_remaining_display',
        currency_field='currency_id', readonly=True,
        help="Amount of this line still available to restate/regroup "
             "(original − already consumed).",
    )
    consume_amount = fields.Monetary(
        string='Consume', currency_field='currency_id', required=True,
        help="Amount of this line to consume now (magnitude). Defaults to "
             "the remaining; must be > 0 and ≤ remaining.",
    )

    @api.depends('move_line_id')
    def _compute_remaining_display(self):
        Trace = self.env['jito.ledger.trace']
        rem = Trace.remaining_to_adjust(self.mapped('move_line_id'))
        for row in self:
            # remaining is signed; users work with magnitudes.
            row.remaining_display = abs(rem.get(row.move_line_id.id, 0.0))

    @api.onchange('move_line_id')
    def _onchange_default_consume(self):
        if self.move_line_id and not self.consume_amount:
            self.consume_amount = self.remaining_display

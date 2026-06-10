# -*- coding: utf-8 -*-

from odoo import api, fields, models


class ScaJournalMap(models.Model):
    _name = 'sca.journal.map'
    _description = 'Crypto Address+Token ↔ Odoo Journal Mapping'
    _order = 'watched_address_id, token_symbol'

    watched_address_id = fields.Many2one(
        'sca.watched_address', string='Watched Address',
        required=True, ondelete='cascade', index=True,
    )
    token_id = fields.Many2one(
        'sca.token', string='Token', required=True,
        domain="[('watched_address_id', '=', watched_address_id)]",
        ondelete='cascade',
    )
    token_symbol = fields.Char(
        string='Token Symbol',
        compute='_compute_token_symbol', store=True, index=True,
    )
    journal_id = fields.Many2one(
        'account.journal', string='Odoo Bank Journal',
        domain="[('type', '=', 'bank')]",
    )
    currency_id = fields.Many2one('res.currency', string='Currency')

    _sql_constraints = [
        ('unique_address_token', 'UNIQUE(watched_address_id, token_symbol)',
         'Each address + token combination can only be mapped once.'),
    ]

    @api.depends('token_id', 'token_id.name')
    def _compute_token_symbol(self):
        for rec in self:
            rec.token_symbol = rec.token_id.name if rec.token_id else False

    @api.onchange('watched_address_id')
    def _onchange_watched_address_id(self):
        """Clear token when address changes to avoid stale selection."""
        self.token_id = False

    def name_get(self):
        return [
            (rec.id, '%s / %s' % (rec.watched_address_id.name or '', rec.token_symbol or ''))
            for rec in self
        ]

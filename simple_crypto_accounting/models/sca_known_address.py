from odoo import api, models, fields


class ScaKnownAddress(models.Model):
    _name = 'sca.known_address'
    _description = 'Known Crypto Address'
    _order = 'partner_id, address'

    # 17.0.10.0.0 — name is now optional. Addresses added from a contact's
    # Crypto Addresses tab capture only (address, note); the alias stays
    # available for standalone Known Addresses rows.
    name = fields.Char(string='Name / Alias')
    address = fields.Char(string='Address', required=True)
    notes = fields.Char(string='Notes')
    # 17.0.10.0.0 — link a wallet address to a normal Odoo contact. Managed
    # only inside the crypto module (this field is never placed on the stock
    # partner form), so wallet addresses stay confined to the crypto app.
    partner_id = fields.Many2one(
        'res.partner',
        string='Contact',
        ondelete='cascade',
        index=True,
        help="The Odoo contact this wallet address belongs to. Used to "
             "resolve the counterparty partner when injecting transactions "
             "into the Management Ledger.",
    )

    _sql_constraints = [
        ('unique_address', 'UNIQUE(address)', 'This address is already registered as a known address.'),
    ]

    @api.depends('name', 'address')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = rec.name or rec.address or ''

from odoo import api, models, fields


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # 17.0.10.0.0 — crypto wallet addresses owned by this contact. The field
    # lives on the model but is referenced ONLY in the crypto module's custom
    # contact form (never in base.view_partner_form), so the addresses appear
    # exclusively inside the Crypto app. The rows themselves are ACL-locked to
    # the crypto groups on sca.known_address.
    crypto_address_ids = fields.One2many(
        'sca.known_address', 'partner_id',
        string='Crypto Addresses',
    )
    crypto_address_count = fields.Integer(
        string='Crypto Addresses',
        compute='_compute_crypto_address_count',
    )

    @api.depends('crypto_address_ids')
    def _compute_crypto_address_count(self):
        for partner in self:
            partner.crypto_address_count = len(partner.crypto_address_ids)

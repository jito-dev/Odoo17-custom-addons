from odoo import models, fields


class ScaKnownAddress(models.Model):
    _name = 'sca.known_address'
    _description = 'Known Crypto Address'
    _order = 'name'

    name = fields.Char(string='Name / Alias', required=True)
    address = fields.Char(string='Address', required=True)
    notes = fields.Char(string='Notes')

    _sql_constraints = [
        ('unique_address', 'UNIQUE(address)', 'This address is already registered as a known address.'),
    ]

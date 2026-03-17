from odoo import fields, models


class SecretTag(models.Model):
    _name = 'secret.tag'
    _description = 'Secret Tag'
    _order = 'name'

    name = fields.Char(string='Tag', required=True, translate=True)
    color = fields.Integer(string='Color Index', default=0)

    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'Tag name must be unique.'),
    ]

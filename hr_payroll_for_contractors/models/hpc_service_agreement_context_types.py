from odoo import fields, models


class HpcLegalEntityType(models.Model):
    """Catalogue of legal entity types used as filter criteria on service agreements."""
    _name = 'hpc.legal.entity.type'
    _description = 'Legal Entity Type'
    _order = 'sequence, id'

    code = fields.Char(string='Code', required=True)
    name = fields.Char(string='Name', required=True)
    sequence = fields.Integer(default=10)

    _sql_constraints = [
        ('unique_code', 'UNIQUE(code)', 'Legal entity type code must be unique.'),
    ]


class HpcPaymentMethodType(models.Model):
    """Catalogue of payment method types used as filter criteria on service agreements."""
    _name = 'hpc.payment.method.type'
    _description = 'Payment Method Type'
    _order = 'sequence, id'

    code = fields.Char(string='Code', required=True)
    name = fields.Char(string='Name', required=True)
    sequence = fields.Integer(default=10)

    _sql_constraints = [
        ('unique_code', 'UNIQUE(code)', 'Payment method type code must be unique.'),
    ]

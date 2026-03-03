from odoo import models, fields


class CostEstimatorAdminConfig(models.Model):
    _name = "cost.estimator.admin.config"
    _description = "Admin config"

    category = fields.Char(string="Admin Category", required=True)
    multiplier = fields.Selection(selection=[
        ('default', 'x1'),
        ('1.2', 'x1.2'),
        ('1.25', 'x1.25'),
        ('1.3', 'x1.3'),
        ('1.4', 'x1.4'),
        ('1.5', 'x1.5'),
        ('2', 'x2'),
        ('3', 'x3')
    ], string="Multiplier")
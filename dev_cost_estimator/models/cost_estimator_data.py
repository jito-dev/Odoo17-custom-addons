from odoo import models, fields


class CostEstimatorData(models.Model):
    _name = "cost.estimator.data"
    _description = "Cost estimator data"

    category_id = fields.Many2one("cost.estimator.category", string="Category")
    exp = fields.Integer(string='Years of experience')

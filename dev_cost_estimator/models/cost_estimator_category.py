from odoo import models, fields


class CostEstimatorCategory(models.Model):
    _name = "cost.estimator.category"
    _description = "Job category for cost estimator"

    name = fields.Char(string="Category", required=True)
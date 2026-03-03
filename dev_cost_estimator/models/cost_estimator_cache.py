# -*- coding: utf-8 -*-
from datetime import timedelta
from odoo import models, fields


class CostEstimatorCache(models.Model):
    _name = "cost.estimator.cache"
    _description = "Cost Estimator Cache"
    _rec_name = "category_id"

    category_id = fields.Many2one(
        "cost.estimator.category",
        string="Category",
        required=False,
        ondelete="cascade",
    )
    exp = fields.Selection([
        ('any', 'Any'),
        ('0', '< 1 year'),
        ('1', '1-2 years'),
        ('2', '2-3 years'),
        ('3', '3-5 years'),
        ('5', '5+ years'),
    ], string="Experience", default='any')

    avg_min = fields.Integer(string="Avg Min Salary")
    avg_max = fields.Integer(string="Avg Max Salary")
    online_count = fields.Integer(string="Candidates Online")
    chart_data = fields.Text(string="Chart Data (JSON)")
    cached_at = fields.Datetime(string="Cached At", default=fields.Datetime.now)

    _sql_constraints = [
        (
            'unique_category_exp',
            'UNIQUE(category_id, exp)',
            'Cache entry must be unique per category and experience level.',
        )
    ]

    def is_fresh(self, hours=24):
        """Return True if this cache entry is younger than `hours` hours."""
        self.ensure_one()
        if not self.cached_at:
            return False
        cutoff = fields.Datetime.now() - timedelta(hours=hours)
        return self.cached_at >= cutoff

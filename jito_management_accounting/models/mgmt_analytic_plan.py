from odoo import models, fields


class MgmtAnalyticPlan(models.Model):
    _name = 'mgmt.analytic.plan'
    _description = 'Management Analytic Plan'
    _order = 'sequence, id'

    name = fields.Char(
        string='Name',
        required=True,
    )
    sequence = fields.Integer(
        string='Sequence',
        default=10,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    active = fields.Boolean(
        string='Active',
        default=True,
    )
    account_ids = fields.One2many(
        'mgmt.analytic.account',
        'plan_id',
        string='Accounts',
    )

# -*- coding: utf-8 -*-

"""ML Analytic Account (17.0.9.0.0).

Parallel to stock ``account.analytic.account``; standalone management
analytic dimension. Hierarchical (`_parent_store`). Display name is
``[code] name`` like stock.
"""

from odoo import api, fields, models
from odoo.osv import expression


class JitoLedgerAnalyticAccount(models.Model):
    _name = 'jito.ledger.analytic.account'
    _description = 'ML Analytic Account'
    _inherit = ['mail.thread']
    _parent_store = True
    _rec_names_search = ['name', 'code']
    _order = 'plan_id, code, name'

    name = fields.Char(string='Analytic Account', required=True, tracking=True)
    code = fields.Char(string='Reference', tracking=True)
    active = fields.Boolean(default=True, tracking=True)

    plan_id = fields.Many2one(
        'jito.ledger.analytic.plan',
        string='Plan', required=True, ondelete='cascade', index=True,
        tracking=True,
    )
    root_plan_id = fields.Many2one(
        'jito.ledger.analytic.plan',
        string='Root Plan', related='plan_id.root_plan_id', store=True,
    )
    parent_id = fields.Many2one(
        'jito.ledger.analytic.account',
        string='Parent', ondelete='cascade', index=True,
        domain="[('plan_id', '=', plan_id)]",
    )
    parent_path = fields.Char(index=True, unaccent=False)
    child_ids = fields.One2many(
        'jito.ledger.analytic.account', 'parent_id', string='Children',
    )
    color = fields.Integer(related='root_plan_id.color')
    partner_id = fields.Many2one(
        'res.partner', string='Customer', tracking=True,
    )
    company_id = fields.Many2one(
        'res.company', string='Company',
        default=lambda self: self.env.company,
    )

    _sql_constraints = [
        (
            'code_plan_company_uniq',
            'unique(code, plan_id, company_id)',
            'An analytic account code must be unique within a plan per company.',
        ),
    ]

    @api.depends('code', 'name')
    def _compute_display_name(self):
        for account in self:
            name = account.name or ''
            if account.code:
                name = f'[{account.code}] {name}'
            account.display_name = name

    @api.model
    def _name_search(self, name, domain=None, operator='ilike', limit=None, order=None):
        domain = domain or []
        if name:
            domain = expression.AND([
                domain,
                ['|', ('code', operator, name), ('name', operator, name)],
            ])
            name = ''
        return super()._name_search(name, domain, operator, limit, order)

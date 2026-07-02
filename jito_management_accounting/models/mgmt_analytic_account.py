from odoo import models, fields, api


class MgmtAnalyticAccount(models.Model):
    _name = 'mgmt.analytic.account'
    _description = 'Management Analytic Account'
    _parent_name = 'parent_id'
    _parent_store = True
    _order = 'plan_id, code, name'
    _rec_name = 'display_name'

    name = fields.Char(
        string='Name',
        required=True,
    )
    code = fields.Char(
        string='Code',
        size=16,
        index=True,
    )
    plan_id = fields.Many2one(
        'mgmt.analytic.plan',
        string='Plan',
        required=True,
        index=True,
        ondelete='cascade',
    )
    parent_id = fields.Many2one(
        'mgmt.analytic.account',
        string='Parent',
        index=True,
        ondelete='cascade',
        domain="[('plan_id', '=', plan_id), '!', ('id', 'child_of', id)]",
    )
    child_ids = fields.One2many(
        'mgmt.analytic.account',
        'parent_id',
        string='Children',
    )
    parent_path = fields.Char(
        index=True,
        unaccent=False,
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
    display_name = fields.Char(
        compute='_compute_display_name',
    )

    _sql_constraints = [
        ('code_plan_company_uniq', 'UNIQUE(code, plan_id, company_id)',
         'Account code must be unique per plan and company.'),
    ]

    @api.depends('name', 'code', 'plan_id.name')
    def _compute_display_name(self):
        for account in self:
            plan = account.plan_id.name or ''
            if account.code:
                account.display_name = f'{plan} / [{account.code}] {account.name}'
            else:
                account.display_name = f'{plan} / {account.name}'

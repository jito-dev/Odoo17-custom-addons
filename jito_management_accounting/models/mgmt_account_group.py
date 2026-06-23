from odoo import models, fields


class MgmtAccountGroup(models.Model):
    _name = 'mgmt.account.group'
    _description = 'Management Account Group'
    _parent_name = 'parent_id'
    _parent_store = True
    _order = 'sequence, code, name'

    name = fields.Char(
        string='Name',
        required=True,
    )
    code = fields.Char(
        string='Code',
        size=16,
    )
    parent_id = fields.Many2one(
        'mgmt.account.group',
        string='Parent Group',
        index=True,
        ondelete='cascade',
    )
    child_ids = fields.One2many(
        'mgmt.account.group',
        'parent_id',
        string='Child Groups',
    )
    parent_path = fields.Char(
        index=True,
        unaccent=False,
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
    account_ids = fields.One2many(
        'mgmt.account',
        'group_id',
        string='Accounts',
    )

    _sql_constraints = [
        ('code_company_uniq', 'UNIQUE(code, company_id)',
         'Group code must be unique per company.'),
    ]

from odoo import models, fields, api


class MgmtAccount(models.Model):
    _name = 'mgmt.account'
    _description = 'Management Account'
    _order = 'code, name'
    _rec_name = 'display_name'

    name = fields.Char(
        string='Name',
        required=True,
    )
    code = fields.Char(
        string='Code',
        size=16,
        required=True,
        index=True,
    )
    account_type = fields.Selection(
        selection=[
            ('income', 'Income'),
            ('expense', 'Expense'),
            ('cost_of_revenue', 'Cost of Revenue'),
            ('overhead', 'Overhead'),
            ('other', 'Other'),
        ],
        string='Type',
        required=True,
        default='expense',
    )
    group_id = fields.Many2one(
        'mgmt.account.group',
        string='Group',
        index=True,
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
    note = fields.Text(
        string='Notes',
    )
    display_name = fields.Char(
        string='Display Name',
        compute='_compute_display_name',
        store=True,
    )

    _sql_constraints = [
        ('code_company_uniq', 'UNIQUE(code, company_id)',
         'Account code must be unique per company.'),
    ]

    @api.depends('code', 'name')
    def _compute_display_name(self):
        for record in self:
            record.display_name = f"{record.code} {record.name}" if record.code else record.name

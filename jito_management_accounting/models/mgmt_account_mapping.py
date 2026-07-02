from odoo import models, fields


class MgmtAccountMapping(models.Model):
    _name = 'mgmt.account.mapping'
    _description = 'Default Classification'
    _order = 'financial_account_id'

    financial_account_id = fields.Many2one(
        'account.account',
        string='Financial Account',
        required=True,
        index=True,
    )
    mgmt_account_id = fields.Many2one(
        'mgmt.account',
        string='Management Account',
        required=True,
        index=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )

    _sql_constraints = [
        ('mapping_uniq', 'UNIQUE(financial_account_id, company_id)',
         'Each financial account can have only one default management mapping per company.'),
    ]

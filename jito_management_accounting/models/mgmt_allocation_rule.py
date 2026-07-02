from odoo import models, fields, api
from odoo.exceptions import UserError


class MgmtAllocationRule(models.Model):
    _name = 'mgmt.allocation.rule'
    _description = 'Management Allocation Rule'
    _order = 'sequence, id'

    name = fields.Char(
        string='Name',
        required=True,
    )
    sequence = fields.Integer(
        string='Sequence',
        default=10,
    )
    active = fields.Boolean(
        string='Active',
        default=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    source_mgmt_account_id = fields.Many2one(
        'mgmt.account',
        string='Source Management Account',
        required=True,
        help='The management account whose balance will be split.',
    )
    method = fields.Selection(
        selection=[
            ('percentage', 'Fixed Percentage'),
            ('fixed_amount', 'Fixed Amount'),
        ],
        string='Allocation Method',
        required=True,
        default='percentage',
    )
    line_ids = fields.One2many(
        'mgmt.allocation.rule.line',
        'rule_id',
        string='Allocation Targets',
    )
    note = fields.Text(
        string='Notes',
    )

    @api.constrains('line_ids', 'method')
    def _check_allocation_lines(self):
        for rule in self:
            if not rule.line_ids:
                raise UserError('Allocation rule must have at least one target line.')
            if rule.method == 'percentage':
                total = sum(rule.line_ids.mapped('percentage'))
                if abs(total - 100.0) > 0.01:
                    raise UserError(
                        f'Allocation percentages must sum to 100%. '
                        f'Current total: {total}%'
                    )


class MgmtAllocationRuleLine(models.Model):
    _name = 'mgmt.allocation.rule.line'
    _description = 'Management Allocation Rule Line'
    _order = 'sequence, id'

    rule_id = fields.Many2one(
        'mgmt.allocation.rule',
        string='Allocation Rule',
        required=True,
        ondelete='cascade',
    )
    target_mgmt_account_id = fields.Many2one(
        'mgmt.account',
        string='Target Management Account',
        required=True,
    )
    percentage = fields.Float(
        string='Percentage (%)',
    )
    fixed_amount = fields.Monetary(
        string='Fixed Amount',
        currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        related='rule_id.company_id.currency_id',
        string='Currency',
    )
    sequence = fields.Integer(
        string='Sequence',
        default=10,
    )

from odoo import models, fields, api
from odoo.exceptions import ValidationError


class MgmtMappingRuleLine(models.Model):
    _name = 'mgmt.mapping.rule.line'
    _description = 'Classification Rule Target Line'
    _order = 'sequence, id'

    rule_id = fields.Many2one(
        'mgmt.mapping.rule',
        string='Classification Rule',
        required=True,
        ondelete='cascade',
    )
    sequence = fields.Integer(
        string='Sequence',
        default=10,
    )
    target_mgmt_account_id = fields.Many2one(
        'mgmt.account',
        string='Target Management Account',
        required=True,
    )
    percentage = fields.Float(
        string='Percentage',
        required=True,
        digits=(5, 2),
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Partner Override',
    )
    mgmt_analytic_account_ids = fields.Many2many(
        'mgmt.analytic.account',
        'mgmt_mapping_rule_line_mgmt_analytic_rel',
        'rule_line_id',
        'analytic_account_id',
        string='Mgmt Analytics',
    )
    project_id = fields.Many2one(
        'project.project',
        string='Project',
    )

    def action_open_analytic_picker(self):
        """Open the analytics picker popup for this rule line."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Set Analytics',
            'res_model': 'mgmt.analytic.picker',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_target_model': self._name,
                'default_target_id': self.id,
            },
        }

    @api.constrains('mgmt_analytic_account_ids')
    def _check_one_account_per_plan(self):
        for record in self:
            plan_ids = record.mgmt_analytic_account_ids.mapped('plan_id').ids
            if len(plan_ids) != len(set(plan_ids)):
                raise ValidationError(
                    'You may select at most one management analytic account per plan.'
                )

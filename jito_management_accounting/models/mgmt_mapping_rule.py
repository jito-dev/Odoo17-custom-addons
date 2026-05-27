from odoo import models, fields, api
from odoo.exceptions import UserError


class MgmtMappingRule(models.Model):
    _name = 'mgmt.mapping.rule'
    _description = 'Classification Rule'
    _order = 'sequence, id'

    name = fields.Char(
        string='Name',
        required=True,
    )
    sequence = fields.Integer(
        string='Sequence',
        default=10,
        help='Lower sequence = higher priority. First matching rule wins.',
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
    # Match criteria (all optional, combined with AND when set)
    match_account_ids = fields.Many2many(
        'account.account',
        'mgmt_mapping_rule_account_rel',
        'rule_id', 'account_id',
        string='Financial Accounts',
    )
    match_journal_ids = fields.Many2many(
        'account.journal',
        'mgmt_mapping_rule_journal_rel',
        'rule_id', 'journal_id',
        string='Journals',
    )
    match_partner_ids = fields.Many2many(
        'res.partner',
        'mgmt_mapping_rule_partner_rel',
        'rule_id', 'partner_id',
        string='Partners',
    )
    match_label_contains = fields.Char(
        string='Label Contains',
        help='Substring match on source line label (case-insensitive).',
    )
    match_ref_contains = fields.Char(
        string='Reference Contains',
        help='Substring match on source reference (case-insensitive).',
    )
    match_analytic_account_ids = fields.Many2many(
        'account.analytic.account',
        'mgmt_mapping_rule_analytic_rel',
        'rule_id', 'analytic_account_id',
        string='Analytic Accounts',
    )
    match_product_ids = fields.Many2many(
        'product.product',
        'mgmt_mapping_rule_product_rel',
        'rule_id', 'product_id',
        string='Products',
    )
    match_date_from = fields.Date(
        string='Date From',
    )
    match_date_to = fields.Date(
        string='Date To',
    )
    match_amount_min = fields.Float(
        string='Min Amount (abs)',
        help='Match lines where abs(balance) >= this value.',
    )
    match_amount_max = fields.Float(
        string='Max Amount (abs)',
        help='Match lines where abs(balance) <= this value.',
    )
    # Output — single target (legacy, still used when no multi-target lines)
    target_mgmt_account_id = fields.Many2one(
        'mgmt.account',
        string='Target Management Account',
    )
    # Multi-target split
    target_line_ids = fields.One2many(
        'mgmt.mapping.rule.line',
        'rule_id',
        string='Target Split Lines',
    )
    is_multi_target = fields.Boolean(
        string='Multi-Target',
        compute='_compute_is_multi_target',
        store=True,
    )
    mgmt_analytic_account_ids = fields.Many2many(
        'mgmt.analytic.account',
        'mgmt_mapping_rule_mgmt_analytic_rel',
        'rule_id',
        'analytic_account_id',
        string='Mgmt Analytics',
    )
    project_id = fields.Many2one(
        'project.project',
        string='Project',
    )
    note = fields.Text(
        string='Notes',
    )

    def action_open_analytic_picker(self):
        """Open the analytics picker popup for this mapping rule."""
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
                raise UserError(
                    'You may select at most one management analytic account per plan.'
                )

    @api.depends('target_line_ids')
    def _compute_is_multi_target(self):
        for rule in self:
            rule.is_multi_target = bool(rule.target_line_ids)

    @api.constrains('target_mgmt_account_id', 'target_line_ids')
    def _check_target(self):
        for rule in self:
            if rule.target_line_ids:
                total_pct = sum(rule.target_line_ids.mapped('percentage'))
                if abs(total_pct - 100.0) > 0.01:
                    raise UserError(
                        f'Rule "{rule.name}": multi-target percentages must sum to 100% '
                        f'(currently {total_pct:.2f}%).'
                    )
            elif not rule.target_mgmt_account_id:
                raise UserError(
                    f'Rule "{rule.name}": either set a target account or add multi-target split lines.'
                )

    def _match(self, source_line):
        """Check if a mgmt.source.line matches this rule.

        All configured criteria are combined with AND.
        Empty criteria are skipped (they match everything).
        """
        self.ensure_one()

        if self.match_account_ids and source_line.financial_account_id not in self.match_account_ids:
            return False
        if self.match_journal_ids and source_line.journal_id not in self.match_journal_ids:
            return False
        if self.match_partner_ids and source_line.partner_id not in self.match_partner_ids:
            return False
        if self.match_label_contains:
            if self.match_label_contains.lower() not in (source_line.label or '').lower():
                return False
        if self.match_ref_contains:
            if self.match_ref_contains.lower() not in (source_line.ref or '').lower():
                return False
        if self.match_product_ids and source_line.product_id not in self.match_product_ids:
            return False
        if self.match_analytic_account_ids and source_line.analytic_distribution:
            analytic_ids = set()
            for key in source_line.analytic_distribution.keys():
                for part in str(key).split(','):
                    try:
                        analytic_ids.add(int(part))
                    except (ValueError, TypeError):
                        pass
            rule_analytic_ids = set(self.match_analytic_account_ids.ids)
            if not rule_analytic_ids & analytic_ids:
                return False
        elif self.match_analytic_account_ids:
            return False
        if self.match_date_from and source_line.date and source_line.date < self.match_date_from:
            return False
        if self.match_date_to and source_line.date and source_line.date > self.match_date_to:
            return False
        abs_balance = abs(source_line.balance or 0)
        if self.match_amount_min and abs_balance < self.match_amount_min:
            return False
        if self.match_amount_max and abs_balance > self.match_amount_max:
            return False

        return True

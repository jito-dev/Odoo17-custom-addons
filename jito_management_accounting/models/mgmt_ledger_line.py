from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError


class MgmtLedgerLine(models.Model):
    _name = 'mgmt.ledger.line'
    _description = 'Management Ledger Line'
    _order = 'date desc, id desc'
    _rec_name = 'display_name'

    period_id = fields.Many2one(
        'mgmt.period',
        string='Period',
        required=True,
        index=True,
        ondelete='cascade',
    )
    mgmt_account_id = fields.Many2one(
        'mgmt.account',
        string='Management Account',
        required=True,
        index=True,
    )
    date = fields.Date(
        string='Date',
        required=True,
        index=True,
    )
    label = fields.Char(
        string='Label',
    )
    debit = fields.Monetary(
        string='Debit',
        currency_field='currency_id',
    )
    credit = fields.Monetary(
        string='Credit',
        currency_field='currency_id',
    )
    balance = fields.Monetary(
        string='Balance',
        currency_field='currency_id',
        compute='_compute_balance',
        store=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        required=True,
        default=lambda self: self.env.company.currency_id,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        index=True,
        default=lambda self: self.env.company,
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Partner',
    )
    analytic_distribution = fields.Json(
        string='Analytic Distribution',
    )
    mgmt_analytic_account_ids = fields.Many2many(
        'mgmt.analytic.account',
        'mgmt_ledger_line_analytic_account_rel',
        'ledger_line_id',
        'analytic_account_id',
        string='Mgmt Analytics',
    )
    mgmt_analytic_distribution = fields.Json(
        string='Mgmt Analytic Distribution',
        help='JSON mapping account IDs to percentages, e.g. {"5": 60.0, "7": 40.0}',
    )
    project_id = fields.Many2one(
        'project.project',
        string='Project',
    )
    # Reference currency (optional — tracks economic currency when different from booking currency)
    ref_currency_id = fields.Many2one(
        'res.currency',
        string='Ref. Currency',
    )
    ref_amount = fields.Float(
        string='Ref. Amount',
        digits=(16, 2),
    )
    # Matching
    matching_number = fields.Char(
        string='Matching Number',
        index=True,
        copy=False,
    )
    # Origin traceability
    origin_type = fields.Selection(
        selection=[
            ('source', 'Source Ingestion'),
            ('mapping', 'Classification'),
            ('allocation', 'Allocation'),
            ('timing', 'Timing Adjustment'),
            ('manual', 'Journal Entry'),
            ('matching', 'Matching Write-off'),
        ],
        string='Origin',
        required=True,
        index=True,
    )
    source_line_id = fields.Many2one(
        'mgmt.source.line',
        string='Source Line',
        index=True,
    )
    source_move_line_id = fields.Many2one(
        'account.move.line',
        string='Financial Journal Item',
        index=True,
    )
    mapping_rule_id = fields.Many2one(
        'mgmt.mapping.rule',
        string='Classification Rule',
    )
    allocation_rule_id = fields.Many2one(
        'mgmt.allocation.rule',
        string='Allocation Rule',
    )
    timing_rule_id = fields.Many2one(
        'mgmt.timing.rule',
        string='Timing Rule',
    )
    adjustment_id = fields.Many2one(
        'mgmt.manual.adjustment',
        string='Journal Entry',
    )
    display_name = fields.Char(
        string='Display Name',
        compute='_compute_display_name',
    )
    mgmt_account_type = fields.Selection(
        related='mgmt_account_id.account_type',
        string='Account Type',
        store=True,
    )
    mgmt_account_group_id = fields.Many2one(
        related='mgmt_account_id.group_id',
        string='Account Group',
        store=True,
    )

    @api.constrains('mgmt_analytic_account_ids')
    def _check_one_account_per_plan(self):
        for record in self:
            plan_ids = record.mgmt_analytic_account_ids.mapped('plan_id').ids
            if len(plan_ids) != len(set(plan_ids)):
                raise ValidationError(
                    'You may select at most one management analytic account per plan.'
                )

    @api.depends('debit', 'credit')
    def _compute_balance(self):
        for line in self:
            line.balance = line.debit - line.credit

    def _compute_display_name(self):
        for record in self:
            account = record.mgmt_account_id.display_name or ''
            label = record.label or ''
            record.display_name = f"{account} - {label}" if label else account

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            period_id = vals.get('period_id')
            if period_id:
                period = self.env['mgmt.period'].browse(period_id)
                period._check_period_open()
        return super().create(vals_list)

    def write(self, vals):
        for line in self:
            line.period_id._check_period_open()
        return super().write(vals)

    def unlink(self):
        for line in self:
            line.period_id._check_period_open()
        return super().unlink()

    def action_unclassify(self):
        """Remove this classification ledger line and reset its source line to draft."""
        for line in self:
            if line.origin_type != 'mapping':
                raise UserError('Only classification lines can be unclassified.')
            line.period_id._check_period_open()
            source = line.source_line_id
            line.unlink()
            # If the source line has no more mapping ledger lines, reset to draft
            if source and not source.ledger_line_ids.filtered(
                lambda l: l.origin_type == 'mapping'
            ):
                source.state = 'draft'

    def action_open_analytic_picker(self):
        """Open the analytics picker popup for this ledger line."""
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

    def action_unmatch(self):
        """Clear matching and delete write-off lines for the given matching numbers."""
        matching_numbers = set(self.mapped('matching_number')) - {False}
        if not matching_numbers:
            raise UserError('No matching number on selected lines.')
        for mn in matching_numbers:
            matched_lines = self.search([('matching_number', '=', mn)])
            # Check all periods are open
            for line in matched_lines:
                line.period_id._check_period_open()
            # Delete write-off lines (origin_type='matching')
            writeoff_lines = matched_lines.filtered(lambda l: l.origin_type == 'matching')
            if writeoff_lines:
                writeoff_lines.unlink()
            # Clear matching_number on remaining lines
            remaining = matched_lines.filtered(lambda l: l.origin_type != 'matching')
            remaining.write({'matching_number': False})

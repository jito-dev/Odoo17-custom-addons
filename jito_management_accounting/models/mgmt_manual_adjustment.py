from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError


class MgmtManualAdjustment(models.Model):
    _name = 'mgmt.manual.adjustment'
    _description = 'Management Journal Entry'
    _inherit = ['mail.thread']
    _order = 'date desc, id desc'

    journal_type = fields.Selection(
        selection=[
            ('general', 'General'),
            ('receivable', 'Receivable'),
            ('payable', 'Payable'),
        ],
        string='Type',
        required=True,
        default='general',
        tracking=True,
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Partner',
        help='Required for receivable/payable journal entries.',
    )
    name = fields.Char(
        string='Reference',
        required=True,
        readonly=True,
        default='New',
        copy=False,
    )
    date = fields.Date(
        string='Date',
        required=True,
        default=fields.Date.context_today,
    )
    period_id = fields.Many2one(
        'mgmt.period',
        string='Period',
        required=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        required=True,
        default=lambda self: self.env.company.currency_id,
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('posted', 'Posted'),
            ('cancelled', 'Cancelled'),
        ],
        string='Status',
        default='draft',
        tracking=True,
    )
    reason = fields.Text(
        string='Reason',
        required=True,
        help='Mandatory justification for this journal entry.',
    )
    line_ids = fields.One2many(
        'mgmt.manual.adjustment.line',
        'adjustment_id',
        string='Adjustment Lines',
    )
    total_debit = fields.Monetary(
        string='Total Debit',
        compute='_compute_totals',
        currency_field='currency_id',
    )
    total_credit = fields.Monetary(
        string='Total Credit',
        compute='_compute_totals',
        currency_field='currency_id',
    )
    is_balanced = fields.Boolean(
        string='Is Balanced',
        compute='_compute_totals',
    )
    ledger_line_ids = fields.One2many(
        'mgmt.ledger.line',
        'adjustment_id',
        string='Generated Ledger Lines',
    )

    @api.depends('line_ids.debit', 'line_ids.credit')
    def _compute_totals(self):
        for adj in self:
            adj.total_debit = sum(adj.line_ids.mapped('debit'))
            adj.total_credit = sum(adj.line_ids.mapped('credit'))
            adj.is_balanced = adj.company_id.currency_id.is_zero(
                adj.total_debit - adj.total_credit
            )

    @api.constrains('journal_type', 'partner_id')
    def _check_partner_required(self):
        for adj in self:
            if adj.journal_type in ('receivable', 'payable') and not adj.partner_id:
                raise UserError('Partner is required for receivable/payable journal entries.')

    @api.onchange('journal_type')
    def _onchange_journal_type(self):
        if self.journal_type in ('receivable', 'payable') and not self.line_ids:
            config = self.env['mgmt.config']._get_singleton()
            account = False
            if self.journal_type == 'receivable':
                account = config.default_receivable_account_id
            elif self.journal_type == 'payable':
                account = config.default_payable_account_id
            if account:
                self.line_ids = [(0, 0, {
                    'mgmt_account_id': account.id,
                    'label': self.journal_type.capitalize(),
                    'partner_id': self.partner_id.id if self.partner_id else False,
                })]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'mgmt.manual.adjustment'
                ) or 'New'
        return super().create(vals_list)

    def action_post(self):
        for adj in self:
            if adj.state != 'draft':
                raise UserError('Only draft journal entries can be posted.')
            if not adj.is_balanced:
                raise UserError(
                    'Journal entry must be balanced (total debit = total credit) before posting.'
                )
            adj.period_id._check_period_open()
            adj._create_ledger_lines()
            adj.state = 'posted'

    def action_cancel(self):
        for adj in self:
            if adj.state != 'posted':
                raise UserError('Only posted journal entries can be cancelled.')
            adj.period_id._check_period_open()
            adj.ledger_line_ids.unlink()
            adj.state = 'cancelled'

    def action_draft(self):
        for adj in self:
            if adj.state != 'cancelled':
                raise UserError('Only cancelled journal entries can be reset to draft.')
            adj.state = 'draft'

    def _create_ledger_lines(self):
        """Create management ledger lines from adjustment lines."""
        self.ensure_one()
        LedgerLine = self.env['mgmt.ledger.line']
        for line in self.line_ids:
            LedgerLine.create({
                'period_id': self.period_id.id,
                'mgmt_account_id': line.mgmt_account_id.id,
                'date': self.date,
                'label': line.label or f'MJE: {self.name}',
                'debit': line.debit,
                'credit': line.credit,
                'currency_id': self.currency_id.id,
                'company_id': self.company_id.id,
                'partner_id': line.partner_id.id if line.partner_id else (
                    self.partner_id.id if self.partner_id else False
                ),
                'analytic_distribution': line.analytic_distribution,
                'mgmt_analytic_account_ids': [(6, 0, line.mgmt_analytic_account_ids.ids)],
                'project_id': line.project_id.id if line.project_id else False,
                'ref_currency_id': line.ref_currency_id.id if line.ref_currency_id else False,
                'ref_amount': line.ref_amount,
                'origin_type': 'manual',
                'adjustment_id': self.id,
            })


class MgmtManualAdjustmentLine(models.Model):
    _name = 'mgmt.manual.adjustment.line'
    _description = 'Management Journal Entry Line'
    _order = 'sequence, id'

    @api.constrains('mgmt_analytic_account_ids')
    def _check_one_account_per_plan(self):
        for record in self:
            plan_ids = record.mgmt_analytic_account_ids.mapped('plan_id').ids
            if len(plan_ids) != len(set(plan_ids)):
                raise ValidationError(
                    'You may select at most one management analytic account per plan.'
                )

    def action_open_analytic_picker(self):
        """Open the analytics picker popup for this adjustment line."""
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

    adjustment_id = fields.Many2one(
        'mgmt.manual.adjustment',
        string='Adjustment',
        required=True,
        ondelete='cascade',
    )
    mgmt_account_id = fields.Many2one(
        'mgmt.account',
        string='Management Account',
        required=True,
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
    partner_id = fields.Many2one(
        'res.partner',
        string='Partner',
    )
    analytic_distribution = fields.Json(
        string='Analytic Distribution',
    )
    mgmt_analytic_account_ids = fields.Many2many(
        'mgmt.analytic.account',
        'mgmt_adj_line_analytic_account_rel',
        'adj_line_id',
        'analytic_account_id',
        string='Mgmt Analytics',
    )
    project_id = fields.Many2one(
        'project.project',
        string='Project',
    )
    sequence = fields.Integer(
        string='Sequence',
        default=10,
    )
    currency_id = fields.Many2one(
        related='adjustment_id.currency_id',
        string='Currency',
    )
    ref_currency_id = fields.Many2one(
        'res.currency',
        string='Ref. Currency',
    )
    ref_amount = fields.Float(
        string='Ref. Amount',
        digits=(16, 2),
    )

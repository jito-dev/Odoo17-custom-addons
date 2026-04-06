from odoo import models, fields, api
from odoo.exceptions import UserError


class MgmtManualAdjustment(models.Model):
    _name = 'mgmt.manual.adjustment'
    _description = 'Management Journal Entry'
    _inherit = ['mail.thread']
    _order = 'date desc, id desc'

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
                'partner_id': line.partner_id.id if line.partner_id else False,
                'analytic_distribution': line.analytic_distribution,
                'origin_type': 'manual',
                'adjustment_id': self.id,
            })


class MgmtManualAdjustmentLine(models.Model):
    _name = 'mgmt.manual.adjustment.line'
    _description = 'Management Journal Entry Line'
    _order = 'sequence, id'

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
    sequence = fields.Integer(
        string='Sequence',
        default=10,
    )
    currency_id = fields.Many2one(
        related='adjustment_id.currency_id',
        string='Currency',
    )

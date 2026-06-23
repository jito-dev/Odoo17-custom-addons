from odoo import models, fields, api
from odoo.exceptions import UserError


class MgmtReconciliation(models.Model):
    _name = 'mgmt.reconciliation'
    _description = 'Management Reconciliation'
    _inherit = ['mail.thread']
    _order = 'create_date desc'

    name = fields.Char(
        string='Name',
        compute='_compute_name',
        store=True,
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
    date_run = fields.Datetime(
        string='Run Date',
        default=fields.Datetime.now,
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('done', 'Done'),
        ],
        string='Status',
        default='draft',
    )
    financial_total = fields.Monetary(
        string='Financial Total',
        currency_field='currency_id',
    )
    management_total = fields.Monetary(
        string='Management Total',
        currency_field='currency_id',
    )
    variance = fields.Monetary(
        string='Variance',
        currency_field='currency_id',
        compute='_compute_variance',
        store=True,
    )
    variance_pct = fields.Float(
        string='Variance %',
        compute='_compute_variance',
        store=True,
    )
    line_ids = fields.One2many(
        'mgmt.reconciliation.line',
        'reconciliation_id',
        string='Detail Lines',
    )
    note = fields.Text(
        string='Notes',
    )

    @api.depends('period_id')
    def _compute_name(self):
        for rec in self:
            period_name = rec.period_id.name if rec.period_id else ''
            rec.name = f'Reconciliation - {period_name}'

    @api.depends('financial_total', 'management_total')
    def _compute_variance(self):
        for rec in self:
            rec.variance = rec.financial_total - rec.management_total
            if rec.financial_total:
                rec.variance_pct = (rec.variance / rec.financial_total) * 100
            else:
                rec.variance_pct = 0.0

    def action_compute(self):
        """Calculate financial vs management totals per account."""
        for rec in self:
            if rec.state == 'done':
                raise UserError('Reset to draft before re-computing.')

            rec.line_ids.unlink()

            # Financial totals from source lines
            source_lines = self.env['mgmt.source.line'].search([
                ('period_id', '=', rec.period_id.id),
                ('company_id', '=', rec.company_id.id),
            ])
            financial_total = sum(source_lines.mapped('balance'))

            # Management totals from ledger lines
            ledger_lines = self.env['mgmt.ledger.line'].search([
                ('period_id', '=', rec.period_id.id),
                ('company_id', '=', rec.company_id.id),
            ])
            management_total = sum(ledger_lines.mapped('balance'))

            # Per-account breakdown
            mgmt_accounts = ledger_lines.mapped('mgmt_account_id')
            recon_lines = []
            for account in mgmt_accounts:
                account_ledger = ledger_lines.filtered(
                    lambda l: l.mgmt_account_id == account
                )
                # Financial balance = sum of source lines that mapped to this account
                account_source = account_ledger.filtered(
                    lambda l: l.origin_type == 'mapping'
                )
                fin_bal = sum(account_source.mapped(
                    lambda l: l.source_line_id.balance if l.source_line_id else 0
                ))
                mgmt_bal = sum(account_ledger.mapped('balance'))

                recon_lines.append((0, 0, {
                    'mgmt_account_id': account.id,
                    'financial_balance': fin_bal,
                    'management_balance': mgmt_bal,
                    'currency_id': rec.currency_id.id,
                }))

            rec.write({
                'financial_total': financial_total,
                'management_total': management_total,
                'line_ids': recon_lines,
                'state': 'done',
                'date_run': fields.Datetime.now(),
            })

    def action_reset(self):
        for rec in self:
            rec.line_ids.unlink()
            rec.write({
                'state': 'draft',
                'financial_total': 0,
                'management_total': 0,
            })


class MgmtReconciliationLine(models.Model):
    _name = 'mgmt.reconciliation.line'
    _description = 'Management Reconciliation Line'
    _order = 'mgmt_account_id'

    reconciliation_id = fields.Many2one(
        'mgmt.reconciliation',
        string='Reconciliation',
        required=True,
        ondelete='cascade',
    )
    mgmt_account_id = fields.Many2one(
        'mgmt.account',
        string='Management Account',
        required=True,
    )
    financial_balance = fields.Monetary(
        string='Financial Balance',
        currency_field='currency_id',
    )
    management_balance = fields.Monetary(
        string='Management Balance',
        currency_field='currency_id',
    )
    variance = fields.Monetary(
        string='Variance',
        currency_field='currency_id',
        compute='_compute_variance',
        store=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
    )

    @api.depends('financial_balance', 'management_balance')
    def _compute_variance(self):
        for line in self:
            line.variance = line.financial_balance - line.management_balance

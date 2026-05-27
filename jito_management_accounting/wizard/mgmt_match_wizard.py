from odoo import models, fields, api
from odoo.exceptions import UserError


class MgmtMatchWizard(models.TransientModel):
    _name = 'mgmt.match.wizard'
    _description = 'Match Management Ledger Lines'

    line_ids = fields.Many2many(
        'mgmt.ledger.line',
        string='Lines to Match',
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
    difference = fields.Monetary(
        string='Difference',
        compute='_compute_totals',
        currency_field='currency_id',
    )
    is_balanced = fields.Boolean(
        string='Is Balanced',
        compute='_compute_totals',
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
    )
    writeoff_mgmt_account_id = fields.Many2one(
        'mgmt.account',
        string='Write-off Account',
        help='Management account for the write-off line (required if not balanced).',
    )
    writeoff_label = fields.Char(
        string='Write-off Label',
        default='Matching Write-off',
    )
    writeoff_period_id = fields.Many2one(
        'mgmt.period',
        string='Write-off Period',
    )

    @api.depends('line_ids.debit', 'line_ids.credit')
    def _compute_totals(self):
        for wiz in self:
            wiz.total_debit = sum(wiz.line_ids.mapped('debit'))
            wiz.total_credit = sum(wiz.line_ids.mapped('credit'))
            wiz.difference = wiz.total_debit - wiz.total_credit
            currency = wiz.currency_id or self.env.company.currency_id
            wiz.is_balanced = currency.is_zero(wiz.difference)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_ids = self._context.get('active_ids', [])
        if not active_ids or len(active_ids) < 2:
            raise UserError('Please select at least 2 lines to match.')
        lines = self.env['mgmt.ledger.line'].browse(active_ids)
        already_matched = lines.filtered(lambda l: l.matching_number)
        if already_matched:
            raise UserError(
                'Some selected lines are already matched. Unmatch them first.'
            )
        res['line_ids'] = [(6, 0, lines.ids)]
        # Default write-off period to the most common period among selected lines
        periods = lines.mapped('period_id')
        if periods:
            res['writeoff_period_id'] = periods[0].id
        return res

    def action_match(self):
        self.ensure_one()
        if not self.line_ids or len(self.line_ids) < 2:
            raise UserError('At least 2 lines are required for matching.')

        # Check all periods are open
        for line in self.line_ids:
            line.period_id._check_period_open()

        matching_number = self.env['ir.sequence'].next_by_code('mgmt.matching') or 'MM/00000'

        if not self.is_balanced:
            if not self.writeoff_mgmt_account_id:
                raise UserError('A write-off account is required when lines are not balanced.')
            if not self.writeoff_period_id:
                raise UserError('A write-off period is required when lines are not balanced.')

            self.writeoff_period_id._check_period_open()

            diff = self.difference
            writeoff_vals = {
                'period_id': self.writeoff_period_id.id,
                'mgmt_account_id': self.writeoff_mgmt_account_id.id,
                'date': fields.Date.context_today(self),
                'label': self.writeoff_label or 'Matching Write-off',
                'debit': abs(diff) if diff < 0 else 0,
                'credit': diff if diff > 0 else 0,
                'currency_id': self.currency_id.id,
                'company_id': self.env.company.id,
                'origin_type': 'matching',
                'matching_number': matching_number,
            }
            self.env['mgmt.ledger.line'].create(writeoff_vals)

        self.line_ids.write({'matching_number': matching_number})

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Matched',
                'message': f'Assigned matching number {matching_number} to {len(self.line_ids)} lines.',
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

from odoo import models, fields, api
from odoo.exceptions import UserError


class MgmtTimingRule(models.Model):
    _name = 'mgmt.timing.rule'
    _description = 'Management Timing Adjustment Rule'
    _inherit = ['mail.thread']
    _order = 'id desc'

    name = fields.Char(
        string='Name',
        required=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    source_mgmt_account_id = fields.Many2one(
        'mgmt.account',
        string='Management Account',
        required=True,
    )
    method = fields.Selection(
        selection=[
            ('straight_line', 'Straight-line Spread'),
            ('defer', 'Defer to Future Period'),
            ('accelerate', 'Accelerate to Current Period'),
        ],
        string='Method',
        required=True,
        default='straight_line',
    )
    spread_periods = fields.Integer(
        string='Spread Over Periods',
        help='Number of periods to spread the amount over (for straight-line method).',
    )
    target_period_id = fields.Many2one(
        'mgmt.period',
        string='Target Period',
        help='Target period for defer/accelerate method.',
    )
    source_period_id = fields.Many2one(
        'mgmt.period',
        string='Source Period',
        required=True,
    )
    amount = fields.Monetary(
        string='Amount',
        required=True,
        currency_field='currency_id',
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
            ('applied', 'Applied'),
        ],
        string='Status',
        default='draft',
        tracking=True,
    )
    note = fields.Text(
        string='Notes',
    )
    ledger_line_ids = fields.One2many(
        'mgmt.ledger.line',
        'timing_rule_id',
        string='Generated Ledger Lines',
    )

    def action_apply(self):
        """Generate timing adjustment ledger lines."""
        for rule in self:
            if rule.state != 'draft':
                raise UserError('Only draft timing rules can be applied.')
            rule._generate_timing_lines()
            rule.state = 'applied'

    def action_reverse(self):
        """Remove generated timing lines and reset to draft."""
        for rule in self:
            if rule.state != 'applied':
                raise UserError('Only applied timing rules can be reversed.')
            for line in rule.ledger_line_ids:
                line.period_id._check_period_open()
            rule.ledger_line_ids.unlink()
            rule.state = 'draft'

    def _generate_timing_lines(self):
        """Generate ledger lines based on timing method."""
        self.ensure_one()
        LedgerLine = self.env['mgmt.ledger.line']

        if self.method == 'straight_line':
            self._generate_straight_line(LedgerLine)
        elif self.method == 'defer':
            self._generate_defer(LedgerLine)
        elif self.method == 'accelerate':
            self._generate_accelerate(LedgerLine)

    def _generate_straight_line(self, LedgerLine):
        """Spread amount evenly across consecutive periods."""
        if not self.spread_periods or self.spread_periods < 1:
            raise UserError('Spread periods must be at least 1.')

        periods = self.env['mgmt.period'].search([
            ('company_id', '=', self.company_id.id),
            ('date_start', '>=', self.source_period_id.date_start),
            ('state', 'in', ['open', 'draft']),
        ], order='date_start asc', limit=self.spread_periods)

        if len(periods) < self.spread_periods:
            raise UserError(
                f'Need {self.spread_periods} periods starting from '
                f'{self.source_period_id.name}, but only {len(periods)} found.'
            )

        per_period = self.company_id.currency_id.round(self.amount / self.spread_periods)
        remainder = self.amount - (per_period * self.spread_periods)

        # Reversal in source period (remove original amount)
        LedgerLine.create({
            'period_id': self.source_period_id.id,
            'mgmt_account_id': self.source_mgmt_account_id.id,
            'date': self.source_period_id.date_start,
            'label': f'Timing spread: {self.name} (reversal)',
            'debit': self.amount if self.amount < 0 else 0,
            'credit': self.amount if self.amount > 0 else 0,
            'currency_id': self.currency_id.id,
            'company_id': self.company_id.id,
            'origin_type': 'timing',
            'timing_rule_id': self.id,
        })

        # Spread across periods
        for i, period in enumerate(periods):
            period_amount = per_period
            if i == len(periods) - 1:
                period_amount += remainder
            LedgerLine.create({
                'period_id': period.id,
                'mgmt_account_id': self.source_mgmt_account_id.id,
                'date': period.date_start,
                'label': f'Timing spread: {self.name} ({i + 1}/{self.spread_periods})',
                'debit': period_amount if period_amount > 0 else 0,
                'credit': abs(period_amount) if period_amount < 0 else 0,
                'currency_id': self.currency_id.id,
                'company_id': self.company_id.id,
                'origin_type': 'timing',
                'timing_rule_id': self.id,
            })

    def _generate_defer(self, LedgerLine):
        """Move amount from source period to target period."""
        if not self.target_period_id:
            raise UserError('Target period is required for defer method.')

        # Remove from source period
        LedgerLine.create({
            'period_id': self.source_period_id.id,
            'mgmt_account_id': self.source_mgmt_account_id.id,
            'date': self.source_period_id.date_start,
            'label': f'Timing defer: {self.name} (out)',
            'debit': self.amount if self.amount < 0 else 0,
            'credit': self.amount if self.amount > 0 else 0,
            'currency_id': self.currency_id.id,
            'company_id': self.company_id.id,
            'origin_type': 'timing',
            'timing_rule_id': self.id,
        })

        # Add to target period
        LedgerLine.create({
            'period_id': self.target_period_id.id,
            'mgmt_account_id': self.source_mgmt_account_id.id,
            'date': self.target_period_id.date_start,
            'label': f'Timing defer: {self.name} (in)',
            'debit': self.amount if self.amount > 0 else 0,
            'credit': abs(self.amount) if self.amount < 0 else 0,
            'currency_id': self.currency_id.id,
            'company_id': self.company_id.id,
            'origin_type': 'timing',
            'timing_rule_id': self.id,
        })

    def _generate_accelerate(self, LedgerLine):
        """Move amount from source period to current/target period."""
        if not self.target_period_id:
            raise UserError('Target period is required for accelerate method.')

        # Remove from source period
        LedgerLine.create({
            'period_id': self.source_period_id.id,
            'mgmt_account_id': self.source_mgmt_account_id.id,
            'date': self.source_period_id.date_start,
            'label': f'Timing accelerate: {self.name} (out)',
            'debit': self.amount if self.amount < 0 else 0,
            'credit': self.amount if self.amount > 0 else 0,
            'currency_id': self.currency_id.id,
            'company_id': self.company_id.id,
            'origin_type': 'timing',
            'timing_rule_id': self.id,
        })

        # Add to target period
        LedgerLine.create({
            'period_id': self.target_period_id.id,
            'mgmt_account_id': self.source_mgmt_account_id.id,
            'date': self.target_period_id.date_start,
            'label': f'Timing accelerate: {self.name} (in)',
            'debit': self.amount if self.amount > 0 else 0,
            'credit': abs(self.amount) if self.amount < 0 else 0,
            'currency_id': self.currency_id.id,
            'company_id': self.company_id.id,
            'origin_type': 'timing',
            'timing_rule_id': self.id,
        })

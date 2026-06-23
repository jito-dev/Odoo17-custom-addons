from odoo import models, fields, api
from odoo.exceptions import UserError

# Models that have mgmt_analytic_account_ids and can be targets
_ALLOWED_TARGETS = (
    'mgmt.ledger.line',
    'mgmt.manual.adjustment.line',
    'mgmt.assign.account.wizard.line',
    'mgmt.mapping.rule',
    'mgmt.mapping.rule.line',
)


class MgmtAnalyticPicker(models.TransientModel):
    _name = 'mgmt.analytic.picker'
    _description = 'Management Analytics Picker'

    target_model = fields.Char(
        string='Target Model',
        required=True,
    )
    target_id = fields.Integer(
        string='Target Record ID',
        required=True,
    )
    target_balance = fields.Float(
        string='Line Balance',
        readonly=True,
        digits=(16, 2),
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        readonly=True,
    )
    plan_line_ids = fields.One2many(
        'mgmt.analytic.picker.plan',
        'wizard_id',
        string='Plans',
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        target_model = self._context.get('default_target_model')
        target_id = self._context.get('default_target_id')
        if not target_model or not target_id:
            return res

        res['target_model'] = target_model
        res['target_id'] = target_id

        target_balance = 0.0
        # {plan_id: [(account_id, percentage), ...]}
        existing = {}

        if target_model in _ALLOWED_TARGETS:
            target = self.env[target_model].browse(target_id)
            if target.exists():
                if hasattr(target, 'balance'):
                    target_balance = abs(target.balance or 0.0)
                if hasattr(target, 'currency_id') and target.currency_id:
                    res['currency_id'] = target.currency_id.id

                # Try JSON distribution first (has percentages)
                distribution = {}
                if hasattr(target, 'mgmt_analytic_distribution') and target.mgmt_analytic_distribution:
                    distribution = target.mgmt_analytic_distribution

                if distribution:
                    AnalyticAccount = self.env['mgmt.analytic.account']
                    for account_id_str, pct in distribution.items():
                        account = AnalyticAccount.browse(int(account_id_str))
                        if account.exists():
                            existing.setdefault(account.plan_id.id, []).append(
                                (account.id, pct)
                            )
                elif hasattr(target, 'mgmt_analytic_account_ids') and target.mgmt_analytic_account_ids:
                    for account in target.mgmt_analytic_account_ids:
                        existing.setdefault(account.plan_id.id, []).append(
                            (account.id, 100.0)
                        )

        res['target_balance'] = target_balance

        # Build plan lines — one per existing plan with distributions
        plan_lines = []
        for plan_id, account_entries in existing.items():
            account_lines = []
            for account_id, pct in account_entries:
                account_lines.append((0, 0, {
                    'account_id': account_id,
                    'percentage': pct,
                    'amount': round(target_balance * pct / 100.0, 2) if target_balance else 0.0,
                }))
            plan_lines.append((0, 0, {
                'plan_id': plan_id,
                'line_ids': account_lines,
            }))

        res['plan_line_ids'] = plan_lines
        return res

    def action_apply(self):
        """Write analytics distribution back to the target record."""
        self.ensure_one()
        if self.target_model not in _ALLOWED_TARGETS:
            raise UserError('Invalid target model for analytics picker.')

        target = self.env[self.target_model].browse(self.target_id)
        if not target.exists():
            raise UserError('Target record no longer exists.')

        # Validate per-plan totals
        all_account_ids = []
        distribution = {}
        for plan_line in self.plan_line_ids:
            active = plan_line.line_ids.filtered('account_id')
            if not active:
                continue
            total = sum(l.percentage for l in active)
            if abs(total - 100.0) > 0.01:
                raise UserError(
                    f'Plan "{plan_line.plan_id.name}": percentages must sum to 100% '
                    f'(currently {total:.2f}%).'
                )
            for line in active:
                all_account_ids.append(line.account_id.id)
                distribution[str(line.account_id.id)] = line.percentage

        vals = {'mgmt_analytic_account_ids': [(6, 0, all_account_ids)]}
        if hasattr(target, 'mgmt_analytic_distribution'):
            vals['mgmt_analytic_distribution'] = distribution or False

        target.write(vals)
        return {'type': 'ir.actions.act_window_close'}


class MgmtAnalyticPickerPlan(models.TransientModel):
    _name = 'mgmt.analytic.picker.plan'
    _description = 'Management Analytics Picker - Plan'
    _order = 'sequence, id'

    wizard_id = fields.Many2one(
        'mgmt.analytic.picker',
        string='Wizard',
        required=True,
        ondelete='cascade',
    )
    plan_id = fields.Many2one(
        'mgmt.analytic.plan',
        string='Analytic Plan',
        required=True,
    )
    line_ids = fields.One2many(
        'mgmt.analytic.picker.line',
        'plan_line_id',
        string='Distribution',
    )
    total_percentage = fields.Float(
        string='Total %',
        compute='_compute_totals',
        digits=(5, 2),
    )
    total_amount = fields.Monetary(
        string='Total Amount',
        compute='_compute_totals',
        currency_field='currency_id',
    )
    is_complete = fields.Boolean(
        compute='_compute_totals',
    )
    distribution_summary = fields.Char(
        string='Distribution',
        compute='_compute_totals',
    )
    currency_id = fields.Many2one(
        related='wizard_id.currency_id',
    )
    sequence = fields.Integer(
        related='plan_id.sequence',
        store=True,
    )

    def action_remove(self):
        """Remove this plan line and return to the wizard."""
        self.ensure_one()
        wizard = self.wizard_id
        self.unlink()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'mgmt.analytic.picker',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    @api.depends('line_ids.percentage', 'line_ids.amount', 'line_ids.account_id')
    def _compute_totals(self):
        for plan in self:
            active = plan.line_ids.filtered('account_id')
            plan.total_percentage = sum(active.mapped('percentage'))
            plan.total_amount = sum(active.mapped('amount'))
            plan.is_complete = abs(plan.total_percentage - 100.0) < 0.01 if active else True
            # Summary: "UX 60%, Dev 40%"
            parts = []
            for line in active:
                parts.append(f'{line.account_id.name} {line.percentage:.0f}%')
            plan.distribution_summary = ', '.join(parts) if parts else 'Not set'


class MgmtAnalyticPickerLine(models.TransientModel):
    _name = 'mgmt.analytic.picker.line'
    _description = 'Management Analytics Picker Line'
    _order = 'id'

    plan_line_id = fields.Many2one(
        'mgmt.analytic.picker.plan',
        string='Plan Line',
        required=True,
        ondelete='cascade',
    )
    plan_id = fields.Many2one(
        related='plan_line_id.plan_id',
        store=True,
    )
    account_id = fields.Many2one(
        'mgmt.analytic.account',
        string='Account',
        domain="[('plan_id', '=', plan_id)]",
    )
    percentage = fields.Float(
        string='%',
        default=100.0,
        digits=(5, 2),
    )
    amount = fields.Monetary(
        string='Amount',
        currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        related='plan_line_id.currency_id',
    )
    target_balance = fields.Float(
        related='plan_line_id.wizard_id.target_balance',
    )

    @api.onchange('percentage')
    def _onchange_percentage(self):
        balance = self.target_balance or 0.0
        if not balance:
            return
        implied_amount = balance * (self.percentage or 0.0) / 100.0
        if abs((self.amount or 0.0) - implied_amount) > 0.015:
            self.amount = implied_amount

    @api.onchange('amount')
    def _onchange_amount(self):
        balance = self.target_balance or 0.0
        if balance:
            self.percentage = round((self.amount or 0.0) / balance * 100.0, 2)
        else:
            self.percentage = 0.0

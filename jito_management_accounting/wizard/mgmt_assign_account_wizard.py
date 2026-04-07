from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError


class MgmtAssignAccountWizard(models.TransientModel):
    _name = 'mgmt.assign.account.wizard'
    _description = 'Classify Source Line'

    source_line_id = fields.Many2one(
        'mgmt.source.line',
        string='Source Line',
        required=True,
        readonly=True,
    )
    period_id = fields.Many2one(
        'mgmt.period',
        string='Period',
        required=True,
        readonly=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        readonly=True,
    )
    line_ids = fields.One2many(
        'mgmt.assign.account.wizard.line',
        'wizard_id',
        string='Classification Lines',
    )
    effective_date = fields.Date(
        string='Effective Date',
        help='Default date for all classification lines. Leave empty to use the '
             'source line date. Individual lines can override this in the '
             'Effective Date column.',
    )
    # Read-only source context
    source_date = fields.Date(
        related='source_line_id.date',
        string='Source Date',
        readonly=True,
    )
    financial_account_id = fields.Many2one(
        related='source_line_id.financial_account_id',
        string='Financial Account',
        readonly=True,
    )
    label = fields.Char(
        related='source_line_id.label',
        string='Label',
        readonly=True,
    )
    source_balance = fields.Monetary(
        related='source_line_id.balance',
        string='Balance',
        readonly=True,
        currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        related='source_line_id.currency_id',
        string='Currency',
        readonly=True,
    )
    # Totals
    total_percentage = fields.Float(
        string='Total %',
        compute='_compute_totals',
        digits=(5, 2),
    )
    total_amount = fields.Monetary(
        string='Total Assigned',
        compute='_compute_totals',
        currency_field='currency_id',
    )
    remaining = fields.Monetary(
        string='Remaining',
        compute='_compute_totals',
        currency_field='currency_id',
    )
    remaining_percentage = fields.Float(
        string='Remaining %',
        compute='_compute_totals',
        digits=(5, 2),
    )
    is_fully_assigned = fields.Boolean(
        string='Fully Assigned',
        compute='_compute_totals',
    )

    @api.depends('line_ids.amount', 'source_balance')
    def _compute_totals(self):
        for wiz in self:
            wiz.total_amount = sum(wiz.line_ids.mapped('amount'))
            wiz.remaining = (wiz.source_balance or 0.0) - wiz.total_amount
            # Percentage is informational only
            balance = wiz.source_balance or 0.0
            wiz.total_percentage = (
                (wiz.total_amount / balance * 100.0) if balance else 0.0
            )
            wiz.remaining_percentage = 100.0 - wiz.total_percentage
            currency = wiz.currency_id or wiz.company_id.currency_id
            wiz.is_fully_assigned = currency.is_zero(wiz.remaining) if currency else abs(wiz.remaining) < 0.01

    def action_classify(self):
        """Create ledger lines from classification lines and mark source as processed."""
        self.ensure_one()
        source = self.source_line_id

        if source.state == 'processed':
            raise UserError('This source line has already been classified.')
        if not self.line_ids:
            raise UserError('Please add at least one classification line.')
        if not self.is_fully_assigned:
            raise UserError(
                f'Classification is not complete.\n'
                f'Source balance: {self.source_balance:.2f}\n'
                f'Total assigned: {self.total_amount:.2f}\n'
                f'Remaining: {self.remaining:.2f}'
            )

        source.period_id._check_period_open()

        vals_list = []
        for line in self.line_ids:
            # Derive debit/credit proportionally from the source line
            ratio = line.amount / source.balance if source.balance else 0
            debit = abs(source.debit * ratio)
            credit = abs(source.credit * ratio)

            vals_list.append({
                'period_id': source.period_id.id,
                'mgmt_account_id': line.mgmt_account_id.id,
                'date': line.effective_date or self.effective_date or source.date,
                'label': source.label,
                'debit': debit,
                'credit': credit,
                'currency_id': source.currency_id.id,
                'company_id': source.company_id.id,
                'partner_id': line.partner_id.id if line.partner_id else (
                    source.partner_id.id if source.partner_id else False
                ),
                'analytic_distribution': source.analytic_distribution,
                'origin_type': 'mapping',
                'source_line_id': source.id,
                'source_move_line_id': source.source_move_line_id.id if source.source_move_line_id else False,
                'mgmt_analytic_account_ids': [(6, 0, line.mgmt_analytic_account_ids.ids)],
                'project_id': line.project_id.id if line.project_id else False,
                'ref_currency_id': line.ref_currency_id.id if line.ref_currency_id else False,
                'ref_amount': line.ref_amount,
            })

        self.env['mgmt.ledger.line'].create(vals_list)
        source.state = 'processed'

        if len(self.line_ids) == 1:
            msg = f'Classified to {self.line_ids.mgmt_account_id.display_name}'
        else:
            account_names = ', '.join(self.line_ids.mapped('mgmt_account_id.display_name'))
            msg = f'Split across {len(self.line_ids)} accounts: {account_names}'

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Classified',
                'message': msg,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }


class MgmtAssignAccountWizardLine(models.TransientModel):
    _name = 'mgmt.assign.account.wizard.line'
    _description = 'Classify Source Line Item'
    _order = 'sequence, id'

    wizard_id = fields.Many2one(
        'mgmt.assign.account.wizard',
        string='Wizard',
        required=True,
        ondelete='cascade',
    )
    sequence = fields.Integer(
        string='Sequence',
        default=10,
    )
    mgmt_account_id = fields.Many2one(
        'mgmt.account',
        string='Management Account',
        required=True,
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Partner',
    )
    percentage = fields.Float(
        string='%',
        digits=(5, 2),
    )
    amount = fields.Monetary(
        string='Amount',
        currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        related='wizard_id.currency_id',
        string='Currency',
    )
    effective_date = fields.Date(
        string='Effective Date',
        help='Override the management ledger date for this line. '
             'If empty, uses the wizard-level effective date or the source line date.',
    )
    mgmt_analytic_account_ids = fields.Many2many(
        'mgmt.analytic.account',
        'mgmt_assign_wiz_line_analytic_account_rel',
        'wizard_line_id',
        'analytic_account_id',
        string='Mgmt Analytics',
    )
    project_id = fields.Many2one(
        'project.project',
        string='Project',
    )
    ref_currency_id = fields.Many2one(
        'res.currency',
        string='Ref. Currency',
    )
    ref_amount = fields.Float(
        string='Ref. Amount',
        digits=(16, 2),
    )

    def action_open_analytic_picker(self):
        """Open the analytics picker popup for this wizard line."""
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

    @api.onchange('percentage')
    def _onchange_percentage(self):
        """User typed a percentage — compute amount.
        Guard: only recompute amount if the percentage actually implies a
        different value (beyond rounding tolerance). This prevents the
        cascade from _onchange_amount → percentage change → _onchange_percentage
        from overwriting the authoritative amount with a rounded derivative."""
        balance = self.wizard_id.source_balance or 0.0
        if not balance:
            return
        implied_amount = balance * (self.percentage or 0.0) / 100.0
        # Only update amount if it meaningfully differs from what percentage implies.
        # If they already agree (within rounding), amount was set first — don't touch it.
        if abs((self.amount or 0.0) - implied_amount) > 0.015:
            self.amount = implied_amount

    @api.onchange('amount')
    def _onchange_amount(self):
        """User typed an amount — update percentage display only.
        Amount is authoritative; percentage is derived and display-only."""
        balance = self.wizard_id.source_balance or 0.0
        if balance:
            self.percentage = round((self.amount or 0.0) / balance * 100.0, 2)
        else:
            self.percentage = 0.0

    @api.model
    def default_get(self, fields_list):
        """Default new lines to the remaining unassigned amount."""
        res = super().default_get(fields_list)
        wizard_id = self._context.get('default_wizard_id')
        if wizard_id:
            wizard = self.env['mgmt.assign.account.wizard'].browse(wizard_id)
            if wizard.exists():
                used = sum(wizard.line_ids.mapped('amount'))
                balance = wizard.source_balance or 0.0
                remaining = balance - used
                if balance and abs(remaining) > 0.001:
                    res['amount'] = remaining
                    res['percentage'] = round(remaining / balance * 100.0, 2)
                elif not wizard.line_ids:
                    # First line — default to 100%
                    res['amount'] = balance
                    res['percentage'] = 100.0
                # Pre-fill partner from source line
                source = wizard.source_line_id
                if source and source.partner_id:
                    res['partner_id'] = source.partner_id.id
        return res

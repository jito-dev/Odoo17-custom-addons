# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class TmBillingRunCreateWizardLine(models.TransientModel):
    """
    One line per (client, currency) combination available in the period.
    Each line has a "Create Billing Run" button.
    """

    _name = 'tm.billing.run.create.wizard.line'
    _description = 'Create Billing Run Wizard — Available Combination'
    _order = 'client_name, currency_name'

    wizard_id = fields.Many2one(
        comodel_name='tm.billing.run.create.wizard',
        required=True,
        ondelete='cascade',
    )

    client_id = fields.Many2one('res.partner', string='Client', readonly=True)
    client_name = fields.Char(related='client_id.name', store=True, string='Client Name')

    currency_id = fields.Many2one('res.currency', string='Currency', readonly=True)
    currency_name = fields.Char(related='currency_id.name', store=True, string='Currency Name')

    timesheet_count = fields.Integer(string='Timesheets', readonly=True)
    hours_spent = fields.Float(string='Hours Spent', readonly=True, digits='Hours')
    adjusted_hours = fields.Float(string='Adjusted Hours', readonly=True, digits='Hours')
    amount = fields.Monetary(
        string='Est. Amount',
        readonly=True,
        currency_field='currency_id',
    )

    def action_create_billing_run(self):
        """
        Create a billing run for this (client, currency) combination using the
        wizard's period and options, then navigate to the new billing run.
        """
        self.ensure_one()
        wizard = self.wizard_id

        # Validate timesheets still available (data may have changed)
        timesheets = wizard._get_billable_timesheets(
            client_id=self.client_id.id,
            currency_id=self.currency_id.id,
        )
        if not timesheets:
            raise UserError(_(
                "No billable timesheets found for %(client)s / %(currency)s "
                "in the selected period. They may have already been invoiced "
                "or the rate cards may no longer be locked.",
            ) % {
                'client': self.client_id.name,
                'currency': self.currency_id.name,
            })

        billing_run = self.env['tm.billing.run'].create({
            'client_id': self.client_id.id,
            'currency_id': self.currency_id.id,
            'date_start': wizard.date_start,
            'date_end': wizard.date_end,
            'group_by_project': wizard.group_by_project,
            'group_by_month': wizard.group_by_month,
        })

        # Close the wizard dialog and open the new billing run
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'tm.billing.run',
            'res_id': billing_run.id,
            'view_mode': 'form',
            'target': 'current',
        }


class TmBillingRunCreateWizard(models.TransientModel):
    """
    Wizard to create a Billing Run directly from the Billing Dashboard.

    Workflow:
    1. Opened from dashboard with date_start / date_end pre-filled.
    2. User sets grouping options (Group by Project / Group by Month).
    3. Table shows all (client, currency) combinations that have validated,
       uninvoiced, rate-card-linked timesheets in the period — with a
       "Create Billing Run" button on each row.
    4. Alternatively, user can manually pick client + currency from the
       filtered dropdowns and use the footer button.
    """

    _name = 'tm.billing.run.create.wizard'
    _description = 'Create Billing Run from Dashboard'

    # ========================================================================
    # FIELDS
    # ========================================================================

    date_start = fields.Date(string='Period Start', required=True)
    date_end = fields.Date(string='Period End', required=True)

    # ---- Billing run options ----
    group_by_project = fields.Boolean(
        string='Group by Project',
        default=False,
        help="Create separate billing lines per project",
    )
    group_by_month = fields.Boolean(
        string='Group by Month',
        default=False,
        help="Split billing lines by calendar month within the period",
    )

    # ---- Available combinations (one row per client+currency) ----
    line_ids = fields.One2many(
        comodel_name='tm.billing.run.create.wizard.line',
        inverse_name='wizard_id',
        string='Available Combinations',
        readonly=True,
    )

    # ---- Manual selection (fallback / fine-tuning) ----
    available_client_ids = fields.Many2many(
        comodel_name='res.partner',
        relation='tm_billing_create_wiz_avail_client_rel',
        column1='wizard_id',
        column2='partner_id',
        string='Available Clients',
        compute='_compute_available_clients',
    )

    client_id = fields.Many2one(
        comodel_name='res.partner',
        string='Client',
        help="Only clients with validated, uninvoiced timesheets in the period are shown.",
    )

    available_currency_ids = fields.Many2many(
        comodel_name='res.currency',
        relation='tm_billing_create_wiz_avail_currency_rel',
        column1='wizard_id',
        column2='currency_id',
        string='Available Currencies',
        compute='_compute_available_currencies',
    )

    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        help="Only currencies available for the selected client are shown.",
    )

    # ---- Live preview for manual selection ----
    preview_timesheet_count = fields.Integer(string='Timesheets', compute='_compute_preview')
    preview_hours_spent = fields.Float(string='Hours Spent', compute='_compute_preview', digits='Hours')
    preview_adjusted_hours = fields.Float(string='Adjusted Hours', compute='_compute_preview', digits='Hours')
    preview_amount = fields.Float(string='Est. Billable Amount', compute='_compute_preview', digits=(16, 2))
    preview_currency_id = fields.Many2one('res.currency', compute='_compute_preview', string='Preview Currency')
    preview_ready = fields.Boolean(string='Preview Ready', compute='_compute_preview')

    # ========================================================================
    # HELPERS
    # ========================================================================

    def _get_billable_timesheets(self, client_id=None, currency_id=None):
        """
        Return validated, uninvoiced timesheets with locked rate cards in the
        selected period. Optionally filtered by client and/or currency.
        """
        self.ensure_one()

        domain = [
            ('validated', '=', True),
            ('project_id', '!=', False),
            '|',
                ('timesheet_invoice_id', '=', False),
                ('timesheet_invoice_id.state', '=', 'cancel'),
            ('tm_rate_card_entry_id', '!=', False),
            ('tm_rate_card_entry_id.state', 'in', ['locked', 'invoiced_locked']),
            ('company_id', '=', self.env.company.id),
            ('date', '>=', self.date_start),
            ('date', '<=', self.date_end),
        ]

        timesheets = self.env['account.analytic.line'].search(domain)

        if client_id:
            timesheets = timesheets.filtered(
                lambda ts: (
                    ts.project_id.partner_id and ts.project_id.partner_id.id == client_id
                ) or (
                    ts.tm_rate_card_entry_id
                    and ts.tm_rate_card_entry_id.client_id
                    and ts.tm_rate_card_entry_id.client_id.id == client_id
                )
            )

        if currency_id:
            timesheets = timesheets.filtered(
                lambda ts: ts.tm_rate_card_entry_id.currency_id.id == currency_id
            )

        return timesheets

    def _get_client_for_timesheet(self, ts):
        return ts.project_id.partner_id or (
            ts.tm_rate_card_entry_id and ts.tm_rate_card_entry_id.client_id
        )

    # ========================================================================
    # COMPUTE
    # ========================================================================

    @api.depends('date_start', 'date_end')
    def _compute_available_clients(self):
        for wizard in self:
            if not wizard.date_start or not wizard.date_end:
                wizard.available_client_ids = False
                continue
            timesheets = wizard._get_billable_timesheets()
            client_ids = {
                wizard._get_client_for_timesheet(ts).id
                for ts in timesheets
                if wizard._get_client_for_timesheet(ts)
            }
            wizard.available_client_ids = list(client_ids)

    @api.depends('date_start', 'date_end', 'client_id')
    def _compute_available_currencies(self):
        for wizard in self:
            if not wizard.date_start or not wizard.date_end:
                wizard.available_currency_ids = False
                continue
            timesheets = wizard._get_billable_timesheets(
                client_id=wizard.client_id.id if wizard.client_id else None
            )
            currency_ids = {
                ts.tm_rate_card_entry_id.currency_id.id
                for ts in timesheets
                if ts.tm_rate_card_entry_id and ts.tm_rate_card_entry_id.currency_id
            }
            wizard.available_currency_ids = list(currency_ids)

    @api.depends('client_id', 'currency_id', 'date_start', 'date_end')
    def _compute_preview(self):
        for wizard in self:
            if not wizard.client_id or not wizard.currency_id:
                wizard.preview_timesheet_count = 0
                wizard.preview_hours_spent = 0.0
                wizard.preview_adjusted_hours = 0.0
                wizard.preview_amount = 0.0
                wizard.preview_currency_id = False
                wizard.preview_ready = False
                continue

            timesheets = wizard._get_billable_timesheets(
                client_id=wizard.client_id.id,
                currency_id=wizard.currency_id.id,
            )
            wizard.preview_timesheet_count = len(timesheets)
            wizard.preview_hours_spent = sum(timesheets.mapped('unit_amount'))
            wizard.preview_adjusted_hours = sum(timesheets.mapped('tm_adjusted_hours'))
            wizard.preview_amount = sum(timesheets.mapped('tm_billable_amount'))
            wizard.preview_currency_id = wizard.currency_id
            wizard.preview_ready = bool(timesheets)

    # ========================================================================
    # ONCHANGE
    # ========================================================================

    @api.onchange('client_id')
    def _onchange_client_id(self):
        self.currency_id = False

    # ========================================================================
    # CRUD — populate lines on create
    # ========================================================================

    @api.model_create_multi
    def create(self, vals_list):
        wizards = super().create(vals_list)
        for wizard in wizards:
            wizard._build_opportunity_lines()
        return wizards

    def _build_opportunity_lines(self):
        """
        Scan billable timesheets in the period and create one line per
        (client, currency) combination with aggregated stats.
        """
        self.ensure_one()

        timesheets = self._get_billable_timesheets()
        if not timesheets:
            return

        groups = {}
        for ts in timesheets:
            client = self._get_client_for_timesheet(ts)
            if not client:
                continue
            currency = ts.tm_rate_card_entry_id.currency_id if ts.tm_rate_card_entry_id else None
            if not currency:
                continue
            key = (client.id, currency.id)
            if key not in groups:
                groups[key] = {
                    'client_id': client.id,
                    'currency_id': currency.id,
                    'timesheet_count': 0,
                    'hours_spent': 0.0,
                    'adjusted_hours': 0.0,
                    'amount': 0.0,
                }
            groups[key]['timesheet_count'] += 1
            groups[key]['hours_spent'] += ts.unit_amount
            groups[key]['adjusted_hours'] += ts.tm_adjusted_hours
            groups[key]['amount'] += ts.tm_billable_amount

        Line = self.env['tm.billing.run.create.wizard.line']
        for data in groups.values():
            Line.create({
                'wizard_id': self.id,
                'client_id': data['client_id'],
                'currency_id': data['currency_id'],
                'timesheet_count': data['timesheet_count'],
                'hours_spent': data['hours_spent'],
                'adjusted_hours': data['adjusted_hours'],
                'amount': data['amount'],
            })

    # ========================================================================
    # ACTIONS
    # ========================================================================

    def action_create_billing_run(self):
        """Create a billing run for the manually selected client/currency."""
        self.ensure_one()

        if not self.client_id:
            raise UserError(_("Please select a client."))
        if not self.currency_id:
            raise UserError(_("Please select a currency."))

        timesheets = self._get_billable_timesheets(
            client_id=self.client_id.id,
            currency_id=self.currency_id.id,
        )
        if not timesheets:
            raise UserError(_(
                "No billable timesheets found for %(client)s / %(currency)s "
                "in the selected period.",
            ) % {'client': self.client_id.name, 'currency': self.currency_id.name})

        billing_run = self.env['tm.billing.run'].create({
            'client_id': self.client_id.id,
            'currency_id': self.currency_id.id,
            'date_start': self.date_start,
            'date_end': self.date_end,
            'group_by_project': self.group_by_project,
            'group_by_month': self.group_by_month,
        })

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'tm.billing.run',
            'res_id': billing_run.id,
            'view_mode': 'form',
            'target': 'current',
        }

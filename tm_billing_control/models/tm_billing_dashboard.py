# -*- coding: utf-8 -*-

from datetime import date
from dateutil.relativedelta import relativedelta
from odoo import api, fields, models, _


class TmBillingDashboard(models.TransientModel):
    """
    Billing Dashboard - Period Overview with Navigation

    Interactive dashboard showing billing statistics for a selected period:
    - Hours invoiced
    - Hours to invoice
    - Breakdown by client, project, currency
    - Period navigation (Prev/Next/This Month)
    """

    _name = 'tm.billing.dashboard'
    _description = 'Billing Dashboard'

    # Period Selection
    date_start = fields.Date(
        string='Period Start',
        required=True,
        default=lambda self: date.today().replace(day=1),
    )

    date_end = fields.Date(
        string='Period End',
        required=True,
        default=lambda self: (date.today().replace(day=1) + relativedelta(months=1, days=-1)),
    )

    period_display = fields.Char(
        string='Selected Period',
        compute='_compute_period_display',
        store=False,
    )

    # Dashboard Data Lines
    line_ids = fields.One2many(
        comodel_name='tm.billing.dashboard.line',
        inverse_name='dashboard_id',
        string='Dashboard Lines',
    )

    # Summary Statistics
    total_validated_hours = fields.Float(
        string='Total Validated (Delivered) Hours',
        compute='_compute_totals',
    )

    total_invoiced_hours = fields.Float(
        string='Total Invoiced Hours',
        compute='_compute_totals',
    )

    total_paid_hours = fields.Float(
        string='Total Paid Hours',
        compute='_compute_totals',
    )

    total_to_invoice_hours = fields.Float(
        string='Total To Invoice Hours',
        compute='_compute_totals',
    )

    total_validated_amount = fields.Monetary(
        string='Total Validated (Delivered) Amount',
        currency_field='company_currency_id',
        compute='_compute_totals',
    )

    total_invoiced_amount = fields.Monetary(
        string='Total Invoiced Amount',
        currency_field='company_currency_id',
        compute='_compute_totals',
    )

    total_paid_amount = fields.Monetary(
        string='Total Paid Amount',
        currency_field='company_currency_id',
        compute='_compute_totals',
    )

    total_to_invoice_amount = fields.Monetary(
        string='Total To Invoice Amount',
        currency_field='company_currency_id',
        compute='_compute_totals',
    )

    # Summary - Adjusted Hours
    total_validated_adjusted_hours = fields.Float(
        string='Total Validated Adjusted Hours',
        compute='_compute_totals',
    )

    total_invoiced_adjusted_hours = fields.Float(
        string='Total Invoiced Adjusted Hours',
        compute='_compute_totals',
    )

    total_paid_adjusted_hours = fields.Float(
        string='Total Paid Adjusted Hours',
        compute='_compute_totals',
    )

    total_to_invoice_adjusted_hours = fields.Float(
        string='Total To Invoice Adjusted Hours',
        compute='_compute_totals',
    )

    company_currency_id = fields.Many2one(
        'res.currency',
        string='Company Currency',
        default=lambda self: self.env.company.currency_id,
    )

    # ========================================================================
    # COMPUTED FIELDS
    # ========================================================================

    @api.depends('date_start', 'date_end')
    def _compute_period_display(self):
        """Display selected period in readable format"""
        for dashboard in self:
            if dashboard.date_start and dashboard.date_end:
                # Check if it's a full month
                month_start = dashboard.date_start.replace(day=1)
                month_end = month_start + relativedelta(months=1, days=-1)

                if dashboard.date_start == month_start and dashboard.date_end == month_end:
                    # Full month - show as "January 2026"
                    dashboard.period_display = dashboard.date_start.strftime('%B %Y')
                else:
                    # Custom range
                    dashboard.period_display = f"{dashboard.date_start} to {dashboard.date_end}"
            else:
                dashboard.period_display = "No period selected"

    @api.depends('line_ids', 'line_ids.validated_hours', 'line_ids.invoiced_hours',
                 'line_ids.paid_hours', 'line_ids.to_invoice_hours',
                 'line_ids.validated_adjusted_hours', 'line_ids.invoiced_adjusted_hours',
                 'line_ids.paid_adjusted_hours', 'line_ids.to_invoice_adjusted_hours',
                 'line_ids.validated_amount', 'line_ids.invoiced_amount',
                 'line_ids.paid_amount', 'line_ids.to_invoice_amount')
    def _compute_totals(self):
        """Compute summary statistics from dashboard lines"""
        for dashboard in self:
            # Hours Spent totals (unit_amount)
            dashboard.total_validated_hours = sum(dashboard.line_ids.mapped('validated_hours'))
            dashboard.total_invoiced_hours = sum(dashboard.line_ids.mapped('invoiced_hours'))
            dashboard.total_paid_hours = sum(dashboard.line_ids.mapped('paid_hours'))
            dashboard.total_to_invoice_hours = sum(dashboard.line_ids.mapped('to_invoice_hours'))

            # Adjusted Hours totals (tm_adjusted_hours)
            dashboard.total_validated_adjusted_hours = sum(dashboard.line_ids.mapped('validated_adjusted_hours'))
            dashboard.total_invoiced_adjusted_hours = sum(dashboard.line_ids.mapped('invoiced_adjusted_hours'))
            dashboard.total_paid_adjusted_hours = sum(dashboard.line_ids.mapped('paid_adjusted_hours'))
            dashboard.total_to_invoice_adjusted_hours = sum(dashboard.line_ids.mapped('to_invoice_adjusted_hours'))

            # Convert all amounts to company currency for totals
            company_currency = dashboard.company_currency_id
            total_validated = 0.0
            total_invoiced = 0.0
            total_paid = 0.0
            total_to_invoice = 0.0

            for line in dashboard.line_ids:
                if line.currency_id != company_currency:
                    # Convert to company currency
                    total_validated += line.currency_id._convert(
                        line.validated_amount,
                        company_currency,
                        dashboard.env.company,
                        dashboard.date_end or date.today()
                    )
                    total_invoiced += line.currency_id._convert(
                        line.invoiced_amount,
                        company_currency,
                        dashboard.env.company,
                        dashboard.date_end or date.today()
                    )
                    total_paid += line.currency_id._convert(
                        line.paid_amount,
                        company_currency,
                        dashboard.env.company,
                        dashboard.date_end or date.today()
                    )
                    total_to_invoice += line.currency_id._convert(
                        line.to_invoice_amount,
                        company_currency,
                        dashboard.env.company,
                        dashboard.date_end or date.today()
                    )
                else:
                    total_validated += line.validated_amount
                    total_invoiced += line.invoiced_amount
                    total_paid += line.paid_amount
                    total_to_invoice += line.to_invoice_amount

            dashboard.total_validated_amount = total_validated
            dashboard.total_invoiced_amount = total_invoiced
            dashboard.total_paid_amount = total_paid
            dashboard.total_to_invoice_amount = total_to_invoice

    # ========================================================================
    # ACTIONS - PERIOD NAVIGATION
    # ========================================================================

    def action_previous_month(self):
        """Navigate to previous month"""
        self.ensure_one()

        # Move to previous month
        new_start = self.date_start - relativedelta(months=1)
        new_start = new_start.replace(day=1)
        new_end = new_start + relativedelta(months=1, days=-1)

        self.write({
            'date_start': new_start,
            'date_end': new_end,
        })

        return self.action_refresh_dashboard()

    def action_next_month(self):
        """Navigate to next month"""
        self.ensure_one()

        # Move to next month
        new_start = self.date_start + relativedelta(months=1)
        new_start = new_start.replace(day=1)
        new_end = new_start + relativedelta(months=1, days=-1)

        self.write({
            'date_start': new_start,
            'date_end': new_end,
        })

        return self.action_refresh_dashboard()

    def action_this_month(self):
        """Reset to current month"""
        self.ensure_one()

        today = date.today()
        new_start = today.replace(day=1)
        new_end = new_start + relativedelta(months=1, days=-1)

        self.write({
            'date_start': new_start,
            'date_end': new_end,
        })

        return self.action_refresh_dashboard()

    def action_refresh_dashboard(self):
        """Refresh dashboard data and return to form view"""
        self.ensure_one()

        # Delete existing lines
        self.line_ids.unlink()

        # Generate new lines
        self._generate_dashboard_lines()

        # Return to form view
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'tm.billing.dashboard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_pivot(self):
        """Open pivot view of dashboard lines"""
        self.ensure_one()

        return {
            'name': _('Billing Dashboard - %s') % self.period_display,
            'type': 'ir.actions.act_window',
            'res_model': 'tm.billing.dashboard.line',
            'view_mode': 'pivot,graph,tree',
            'domain': [('dashboard_id', '=', self.id)],
            'context': {
                'search_default_group_by_client': 1,
                'search_default_group_by_status': 1,
            },
        }

    def action_open_billing_runs(self):
        """Navigate to Billing Runs view"""
        return {
            'name': _('Billing Runs'),
            'type': 'ir.actions.act_window',
            'res_model': 'tm.billing.run',
            'view_mode': 'tree,kanban,form',
            'target': 'current',
        }

    def action_create_billing_run(self):
        """Quick action to create a new billing run for selected period"""
        self.ensure_one()

        return {
            'name': _('New Billing Run'),
            'type': 'ir.actions.act_window',
            'res_model': 'tm.billing.run',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_date_start': self.date_start,
                'default_date_end': self.date_end,
                'default_use_current_month': False,
            },
        }

    def action_create_billing_run_wizard(self):
        """
        Open the smart 'Create Billing Run' wizard pre-filled with the current
        dashboard period. Shows available (client, currency) combinations from
        validated, uninvoiced timesheets with locked rate cards in the period.
        """
        self.ensure_one()

        wizard = self.env['tm.billing.run.create.wizard'].create({
            'date_start': self.date_start,
            'date_end': self.date_end,
        })

        return {
            'name': _('Create Billing Run — %s') % self.period_display,
            'type': 'ir.actions.act_window',
            'res_model': 'tm.billing.run.create.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    # ========================================================================
    # DATA GENERATION
    # ========================================================================

    @api.model
    def action_open_dashboard(self):
        """
        Pre-create a fresh dashboard record so that _generate_dashboard_lines()
        fires immediately on open (instead of waiting for the first button click).
        Called by the ir.actions.server menu action.
        """
        dashboard = self.create({})
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'tm.billing.dashboard',
            'res_id': dashboard.id,
            'view_mode': 'form',
            'target': 'current',
        }

    @api.model
    def default_get(self, fields_list):
        """Generate dashboard lines on creation"""
        res = super().default_get(fields_list)
        return res

    @api.model_create_multi
    def create(self, vals_list):
        """Generate dashboard lines after creation (auto-refresh on open)"""
        dashboards = super().create(vals_list)
        for dashboard in dashboards:
            try:
                with self.env.cr.savepoint():
                    dashboard._generate_dashboard_lines()
            except Exception:
                pass  # Never fail dashboard opening due to data generation error
        return dashboards

    def _generate_dashboard_lines(self):
        """
        Generate dashboard lines for the selected period.

        Creates lines grouped by:
        - Client
        - Project
        - Currency
        - Employee

        With metrics breakdown:
        - Validated (all delivered work)
        - Invoiced (with invoice)
        - Paid (fully paid)
        - To Invoice (not yet invoiced)
        """
        self.ensure_one()

        # Get all validated timesheets
        all_timesheets = self._get_all_validated_timesheets()

        # Group and calculate metrics by client/project/employee/currency
        grouped = self._group_timesheets_with_metrics(all_timesheets)

        # Create dashboard lines
        DashboardLine = self.env['tm.billing.dashboard.line']

        for group_key, data in grouped.items():
            # Determine invoice status for filtering
            if data['invoiced_hours'] > 0:
                invoice_status = 'invoiced'
            else:
                invoice_status = 'to_invoice'

            DashboardLine.create({
                'dashboard_id': self.id,
                'client_id': data['client_id'],
                'project_id': data['project_id'],
                'employee_id': data['employee_id'],
                'currency_id': data['currency_id'],
                'invoice_status': invoice_status,
                'validated_hours': data['validated_hours'],
                'invoiced_hours': data['invoiced_hours'],
                'paid_hours': data['paid_hours'],
                'to_invoice_hours': data['to_invoice_hours'],
                'validated_adjusted_hours': data['validated_adjusted_hours'],
                'invoiced_adjusted_hours': data['invoiced_adjusted_hours'],
                'paid_adjusted_hours': data['paid_adjusted_hours'],
                'to_invoice_adjusted_hours': data['to_invoice_adjusted_hours'],
                'validated_amount': data['validated_amount'],
                'invoiced_amount': data['invoiced_amount'],
                'paid_amount': data['paid_amount'],
                'to_invoice_amount': data['to_invoice_amount'],
            })

    def _get_all_validated_timesheets(self):
        """Get all validated timesheets for selected period with rate cards"""
        return self.env['account.analytic.line'].search([
            ('validated', '=', True),
            ('project_id', '!=', False),
            ('employee_id', '!=', False),
            ('tm_rate_card_entry_id', '!=', False),
            ('date', '>=', self.date_start),
            ('date', '<=', self.date_end),
        ])

    def _group_timesheets_with_metrics(self, timesheets):
        """
        Group timesheets by client, project, employee, currency
        Calculate validated, invoiced, paid, and to_invoice metrics
        """
        grouped = {}

        for ts in timesheets:
            # Determine client
            client = ts.project_id.partner_id
            if not client and ts.tm_rate_card_entry_id:
                client = ts.tm_rate_card_entry_id.client_id
            if not client:
                continue

            # Determine currency
            currency = ts.tm_rate_card_entry_id.currency_id if ts.tm_rate_card_entry_id else self.env.company.currency_id

            # Build grouping key (without status)
            key = (client.id, ts.project_id.id, ts.employee_id.id, currency.id)

            if key not in grouped:
                grouped[key] = {
                    'client_id': client.id,
                    'project_id': ts.project_id.id,
                    'employee_id': ts.employee_id.id,
                    'currency_id': currency.id,
                    'validated_hours': 0.0,
                    'invoiced_hours': 0.0,
                    'paid_hours': 0.0,
                    'to_invoice_hours': 0.0,
                    'validated_adjusted_hours': 0.0,
                    'invoiced_adjusted_hours': 0.0,
                    'paid_adjusted_hours': 0.0,
                    'to_invoice_adjusted_hours': 0.0,
                    'validated_amount': 0.0,
                    'invoiced_amount': 0.0,
                    'paid_amount': 0.0,
                    'to_invoice_amount': 0.0,
                }

            hours = ts.unit_amount
            adj_hours = ts.tm_adjusted_hours
            amount = ts.tm_billable_amount if ts.tm_billable_amount else 0.0

            # All validated timesheets count
            grouped[key]['validated_hours'] += hours
            grouped[key]['validated_adjusted_hours'] += adj_hours
            grouped[key]['validated_amount'] += amount

            # Check invoice status
            has_invoice = ts.timesheet_invoice_id and ts.timesheet_invoice_id.state != 'cancel'

            if has_invoice:
                # Has invoice (draft or posted)
                grouped[key]['invoiced_hours'] += hours
                grouped[key]['invoiced_adjusted_hours'] += adj_hours
                grouped[key]['invoiced_amount'] += amount

                # Check if paid
                if ts.timesheet_invoice_id.payment_state in ('paid', 'in_payment'):
                    grouped[key]['paid_hours'] += hours
                    grouped[key]['paid_adjusted_hours'] += adj_hours
                    grouped[key]['paid_amount'] += amount
            else:
                # Not invoiced yet
                grouped[key]['to_invoice_hours'] += hours
                grouped[key]['to_invoice_adjusted_hours'] += adj_hours
                grouped[key]['to_invoice_amount'] += amount

        return grouped


class TmBillingDashboardLine(models.TransientModel):
    """Dashboard line - one row per (client, project, employee, currency, status)"""

    _name = 'tm.billing.dashboard.line'
    _description = 'Billing Dashboard Line'
    _order = 'client_id, project_id, employee_id'

    dashboard_id = fields.Many2one('tm.billing.dashboard', required=True, ondelete='cascade')

    # Dimensions
    client_id = fields.Many2one('res.partner', string='Client', readonly=True)
    project_id = fields.Many2one('project.project', string='Project', readonly=True)
    employee_id = fields.Many2one('hr.employee', string='Employee', readonly=True)
    currency_id = fields.Many2one('res.currency', string='Currency', readonly=True)

    # Status
    invoice_status = fields.Selection([
        ('invoiced', 'Invoiced'),
        ('to_invoice', 'To Invoice'),
    ], string='Status', readonly=True)

    # Metrics - Hours Spent Breakdown (unit_amount — actual logged hours)
    validated_hours = fields.Float(
        string='Validated (Delivered) Hours',
        readonly=True,
        help="All validated timesheets (delivered work — logged hours)"
    )
    invoiced_hours = fields.Float(
        string='Invoiced Hours',
        readonly=True,
        help="Timesheets with invoice created (draft or posted) — logged hours"
    )
    paid_hours = fields.Float(
        string='Paid Hours',
        readonly=True,
        help="Timesheets with fully paid invoice — logged hours"
    )
    to_invoice_hours = fields.Float(
        string='To Invoice Hours',
        readonly=True,
        help="Validated timesheets not yet invoiced — logged hours"
    )
    total_hours = fields.Float(
        string='Total Hours',
        compute='_compute_total_hours',
        store=True
    )

    # Metrics - Adjusted Hours Breakdown (tm_adjusted_hours — billing hours)
    validated_adjusted_hours = fields.Float(
        string='Validated Adjusted Hours',
        readonly=True,
        help="All validated timesheets (delivered work — adjusted billing hours)"
    )
    invoiced_adjusted_hours = fields.Float(
        string='Invoiced Adjusted Hours',
        readonly=True,
        help="Timesheets with invoice created — adjusted billing hours"
    )
    paid_adjusted_hours = fields.Float(
        string='Paid Adjusted Hours',
        readonly=True,
        help="Timesheets with fully paid invoice — adjusted billing hours"
    )
    to_invoice_adjusted_hours = fields.Float(
        string='To Invoice Adjusted Hours',
        readonly=True,
        help="Validated timesheets not yet invoiced — adjusted billing hours"
    )
    total_adjusted_hours = fields.Float(
        string='Total Adjusted Hours',
        compute='_compute_total_adjusted_hours',
        store=True
    )

    # Metrics - Amount Breakdown
    validated_amount = fields.Monetary(
        string='Validated (Delivered) Amount',
        currency_field='currency_id',
        readonly=True,
        help="Total billable amount for all validated timesheets"
    )
    invoiced_amount = fields.Monetary(
        string='Invoiced Amount',
        currency_field='currency_id',
        readonly=True,
        help="Total amount on invoices (draft or posted)"
    )
    paid_amount = fields.Monetary(
        string='Paid Amount',
        currency_field='currency_id',
        readonly=True,
        help="Total amount fully paid"
    )
    to_invoice_amount = fields.Monetary(
        string='To Invoice Amount',
        currency_field='currency_id',
        readonly=True,
        help="Total billable amount not yet invoiced"
    )
    total_amount = fields.Monetary(
        string='Total Amount',
        currency_field='currency_id',
        compute='_compute_total_amount',
        store=True
    )

    @api.depends('validated_hours')
    def _compute_total_hours(self):
        """Total hours equals validated hours (all delivered work)"""
        for line in self:
            line.total_hours = line.validated_hours

    @api.depends('validated_adjusted_hours')
    def _compute_total_adjusted_hours(self):
        """Total adjusted hours equals validated adjusted hours"""
        for line in self:
            line.total_adjusted_hours = line.validated_adjusted_hours

    @api.depends('validated_amount')
    def _compute_total_amount(self):
        """Total amount equals validated amount (all delivered work)"""
        for line in self:
            line.total_amount = line.validated_amount

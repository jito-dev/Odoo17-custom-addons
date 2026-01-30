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
    total_invoiced_hours = fields.Float(
        string='Total Invoiced Hours',
        compute='_compute_totals',
    )

    total_to_invoice_hours = fields.Float(
        string='Total To Invoice Hours',
        compute='_compute_totals',
    )

    total_hours = fields.Float(
        string='Total Hours',
        compute='_compute_totals',
    )

    total_invoiced_amount = fields.Monetary(
        string='Total Invoiced Amount',
        currency_field='company_currency_id',
        compute='_compute_totals',
    )

    total_to_invoice_amount = fields.Monetary(
        string='Total To Invoice Amount',
        currency_field='company_currency_id',
        compute='_compute_totals',
    )

    total_amount = fields.Monetary(
        string='Total Amount',
        currency_field='company_currency_id',
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

    @api.depends('line_ids', 'line_ids.invoiced_hours', 'line_ids.to_invoice_hours',
                 'line_ids.invoiced_amount', 'line_ids.to_invoice_amount')
    def _compute_totals(self):
        """Compute summary statistics from dashboard lines"""
        for dashboard in self:
            dashboard.total_invoiced_hours = sum(dashboard.line_ids.mapped('invoiced_hours'))
            dashboard.total_to_invoice_hours = sum(dashboard.line_ids.mapped('to_invoice_hours'))
            dashboard.total_hours = dashboard.total_invoiced_hours + dashboard.total_to_invoice_hours

            # Convert all amounts to company currency for totals
            company_currency = dashboard.company_currency_id
            total_invoiced = 0.0
            total_to_invoice = 0.0

            for line in dashboard.line_ids:
                if line.currency_id != company_currency:
                    # Convert to company currency
                    total_invoiced += line.currency_id._convert(
                        line.invoiced_amount,
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
                    total_invoiced += line.invoiced_amount
                    total_to_invoice += line.to_invoice_amount

            dashboard.total_invoiced_amount = total_invoiced
            dashboard.total_to_invoice_amount = total_to_invoice
            dashboard.total_amount = total_invoiced + total_to_invoice

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

    # ========================================================================
    # DATA GENERATION
    # ========================================================================

    @api.model
    def default_get(self, fields_list):
        """Generate dashboard lines on creation"""
        res = super().default_get(fields_list)
        return res

    @api.model_create_multi
    def create(self, vals_list):
        """Generate dashboard lines after creation"""
        dashboards = super().create(vals_list)
        for dashboard in dashboards:
            dashboard._generate_dashboard_lines()
        return dashboards

    def _generate_dashboard_lines(self):
        """
        Generate dashboard lines for the selected period.

        Creates lines grouped by:
        - Client
        - Project
        - Currency
        - Employee
        - Status (invoiced / to_invoice)
        """
        self.ensure_one()

        # Get invoiced timesheets
        invoiced_timesheets = self._get_invoiced_timesheets()
        invoiced_grouped = self._group_timesheets(invoiced_timesheets, 'invoiced')

        # Get to-invoice timesheets
        to_invoice_timesheets = self._get_to_invoice_timesheets()
        to_invoice_grouped = self._group_timesheets(to_invoice_timesheets, 'to_invoice')

        # Create dashboard lines
        DashboardLine = self.env['tm.billing.dashboard.line']

        for group_key, data in invoiced_grouped.items():
            DashboardLine.create({
                'dashboard_id': self.id,
                'client_id': data['client_id'],
                'project_id': data['project_id'],
                'employee_id': data['employee_id'],
                'currency_id': data['currency_id'],
                'invoice_status': 'invoiced',
                'invoiced_hours': data['hours'],
                'to_invoice_hours': 0.0,
                'invoiced_amount': data['amount'],
                'to_invoice_amount': 0.0,
            })

        for group_key, data in to_invoice_grouped.items():
            DashboardLine.create({
                'dashboard_id': self.id,
                'client_id': data['client_id'],
                'project_id': data['project_id'],
                'employee_id': data['employee_id'],
                'currency_id': data['currency_id'],
                'invoice_status': 'to_invoice',
                'invoiced_hours': 0.0,
                'to_invoice_hours': data['hours'],
                'invoiced_amount': 0.0,
                'to_invoice_amount': data['amount'],
            })

    def _get_invoiced_timesheets(self):
        """Get invoiced timesheets for selected period"""
        return self.env['account.analytic.line'].search([
            ('validated', '=', True),
            ('project_id', '!=', False),
            ('employee_id', '!=', False),
            ('timesheet_invoice_id', '!=', False),
            ('timesheet_invoice_id.state', '!=', 'cancel'),
            ('date', '>=', self.date_start),
            ('date', '<=', self.date_end),
        ])

    def _get_to_invoice_timesheets(self):
        """Get to-invoice timesheets for selected period"""
        return self.env['account.analytic.line'].search([
            ('validated', '=', True),
            ('project_id', '!=', False),
            ('employee_id', '!=', False),
            '|',
                ('timesheet_invoice_id', '=', False),
                ('timesheet_invoice_id.state', '=', 'cancel'),
            ('tm_rate_card_entry_id', '!=', False),
            ('tm_rate_card_entry_id.state', 'in', ['locked', 'invoiced_locked']),
            ('date', '>=', self.date_start),
            ('date', '<=', self.date_end),
        ])

    def _group_timesheets(self, timesheets, status):
        """Group timesheets by client, project, employee, currency"""
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

            # Build grouping key
            key = (client.id, ts.project_id.id, ts.employee_id.id, currency.id, status)

            if key not in grouped:
                grouped[key] = {
                    'client_id': client.id,
                    'project_id': ts.project_id.id,
                    'employee_id': ts.employee_id.id,
                    'currency_id': currency.id,
                    'hours': 0.0,
                    'amount': 0.0,
                }

            grouped[key]['hours'] += ts.unit_amount
            grouped[key]['amount'] += ts.tm_billable_amount if ts.tm_billable_amount else 0.0

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

    # Metrics
    invoiced_hours = fields.Float(string='Invoiced Hours', readonly=True)
    to_invoice_hours = fields.Float(string='To Invoice Hours', readonly=True)
    total_hours = fields.Float(string='Total Hours', compute='_compute_total_hours', store=True)

    invoiced_amount = fields.Monetary(string='Invoiced Amount', currency_field='currency_id', readonly=True)
    to_invoice_amount = fields.Monetary(string='To Invoice Amount', currency_field='currency_id', readonly=True)
    total_amount = fields.Monetary(string='Total Amount', currency_field='currency_id', compute='_compute_total_amount', store=True)

    @api.depends('invoiced_hours', 'to_invoice_hours')
    def _compute_total_hours(self):
        for line in self:
            line.total_hours = line.invoiced_hours + line.to_invoice_hours

    @api.depends('invoiced_amount', 'to_invoice_amount')
    def _compute_total_amount(self):
        for line in self:
            line.total_amount = line.invoiced_amount + line.to_invoice_amount

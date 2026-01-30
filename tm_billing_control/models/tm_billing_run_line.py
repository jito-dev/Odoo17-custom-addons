# -*- coding: utf-8 -*-

from odoo import api, fields, models, _


class TmBillingRunLine(models.Model):
    """
    Billing Run Line (Grouped Preview)

    Represents a single grouped billing line in a billing run.
    Each line is an immutable snapshot of grouped timesheets by:
    (client, currency, SO line, employee, rate, optional project, optional month)

    These lines become the source for invoice line creation.
    """

    _name = 'tm.billing.run.line'
    _description = 'Billing Run Line (Grouped Preview)'
    _order = 'billing_run_id, sale_order_line_id, employee_id, project_id'
    _rec_name = 'display_name'

    # ========================================================================
    # FIELDS
    # ========================================================================

    # Parent
    billing_run_id = fields.Many2one(
        comodel_name='tm.billing.run',
        string='Billing Run',
        required=True,
        ondelete='cascade',
        index=True,
    )

    # Display name
    display_name = fields.Char(
        string='Name',
        compute='_compute_display_name',
        store=True,
    )

    # Grouping dimensions (snapshot)
    client_id = fields.Many2one(
        comodel_name='res.partner',
        string='Client',
        required=True,
        index=True,
    )

    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        required=True,
    )

    product_id = fields.Many2one(
        comodel_name='product.product',
        string='Service Product',
        required=True,
        index=True,
    )

    employee_id = fields.Many2one(
        comodel_name='hr.employee',
        string='Employee',
        required=True,
        index=True,
    )

    rate = fields.Monetary(
        string='Billing Rate',
        currency_field='currency_id',
        required=True,
        help="Billing rate per hour for this line",
    )

    project_id = fields.Many2one(
        comodel_name='project.project',
        string='Project',
        index=True,
        help="Project (only if grouped by project)",
    )

    period_month = fields.Char(
        string='Period',
        help="Month period (e.g., '2026-01') if grouped by month",
    )

    # Sales Order linkage
    sale_order_line_id = fields.Many2one(
        comodel_name='sale.order.line',
        string='SO Line (Service Bucket)',
        required=True,
        index=True,
        help="Sales Order Line that defines the service bucket for this billing line",
    )

    sale_order_id = fields.Many2one(
        comodel_name='sale.order',
        string='Sales Order',
        related='sale_order_line_id.order_id',
        store=True,
        index=True,
    )

    # Aggregated values
    hours = fields.Float(
        string='Total Hours',
        required=True,
        help="Total hours from grouped timesheets",
    )

    amount = fields.Monetary(
        string='Total Amount',
        currency_field='currency_id',
        required=True,
        help="Total billable amount (hours × rate)",
    )

    # Linked timesheets (Many2many for traceability)
    timesheet_ids = fields.Many2many(
        comodel_name='account.analytic.line',
        relation='tm_billing_run_line_timesheet_rel',
        column1='billing_line_id',
        column2='timesheet_id',
        string='Timesheets',
        help="Timesheets included in this billing line",
    )

    timesheet_count = fields.Integer(
        string='Timesheet Count',
        compute='_compute_timesheet_count',
        store=True,
        help="Number of timesheets in this line",
    )

    # Invoice line link (after invoice creation)
    invoice_line_id = fields.Many2one(
        comodel_name='account.move.line',
        string='Invoice Line',
        readonly=True,
        help="Invoice line created from this billing line",
    )

    invoice_id = fields.Many2one(
        comodel_name='account.move',
        string='Invoice',
        related='billing_run_id.invoice_id',
        store=True,
    )

    # ========================================================================
    # COMPUTED FIELDS
    # ========================================================================

    @api.depends('product_id', 'employee_id', 'project_id', 'period_month', 'hours', 'rate')
    def _compute_display_name(self):
        """Generate readable display name"""
        for line in self:
            parts = []

            # Product + Employee
            if line.product_id and line.employee_id:
                parts.append(f"{line.product_id.name} - {line.employee_id.name}")
            elif line.product_id:
                parts.append(line.product_id.name)

            # Project (if grouped)
            if line.project_id:
                parts.append(f"Project: {line.project_id.name}")

            # Period (if grouped)
            if line.period_month:
                parts.append(f"Period: {line.period_month}")

            # Hours and rate
            parts.append(f"{line.hours}h @ {line.rate} {line.currency_id.symbol or line.currency_id.name}")

            line.display_name = ' | '.join(parts) if parts else 'Billing Line'

    @api.depends('timesheet_ids')
    def _compute_timesheet_count(self):
        """Compute number of linked timesheets"""
        for line in self:
            line.timesheet_count = len(line.timesheet_ids)

    # ========================================================================
    # ACTIONS
    # ========================================================================

    def action_view_timesheets(self):
        """Open linked timesheets in tree view"""
        self.ensure_one()

        return {
            'name': _('Timesheets - %s') % self.display_name,
            'type': 'ir.actions.act_window',
            'res_model': 'account.analytic.line',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', self.timesheet_ids.ids)],
            'context': {
                'create': False,
                'edit': False,
            },
            'target': 'current',
        }

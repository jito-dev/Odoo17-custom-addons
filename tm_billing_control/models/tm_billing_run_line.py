# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError


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

    # Aggregated values (computed from included timesheets)
    hours = fields.Float(
        string='Total Hours',
        compute='_compute_totals',
        store=True,
        help="Total hours from included timesheets",
    )

    amount = fields.Monetary(
        string='Total Amount',
        currency_field='currency_id',
        compute='_compute_totals',
        store=True,
        help="Total billable amount from included timesheets",
    )

    # Timesheet links via intermediary model
    timesheet_line_ids = fields.One2many(
        comodel_name='tm.billing.run.line.timesheet',
        inverse_name='billing_line_id',
        string='Timesheet Lines',
        help="Individual timesheets with inclusion flags",
    )

    # Keep for compatibility (compute from timesheet_line_ids)
    timesheet_ids = fields.Many2many(
        comodel_name='account.analytic.line',
        compute='_compute_timesheet_ids',
        string='Timesheets',
        help="All timesheets in this billing line",
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

    # Readonly control field
    is_readonly = fields.Boolean(
        string='Is Readonly',
        compute='_compute_is_readonly',
        help="True if billing line is frozen (invoice created)",
    )

    # ========================================================================
    # COMPUTED FIELDS
    # ========================================================================

    @api.depends('billing_run_id.state')
    def _compute_is_readonly(self):
        """Mark billing line as readonly after invoice creation"""
        for line in self:
            line.is_readonly = line.billing_run_id.state in ('invoiced', 'closed')

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

    @api.depends('timesheet_line_ids.timesheet_id')
    def _compute_timesheet_ids(self):
        """Compute timesheet_ids from timesheet_line_ids for compatibility"""
        for line in self:
            line.timesheet_ids = line.timesheet_line_ids.mapped('timesheet_id')

    def get_included_timesheets(self):
        """
        Get only the timesheets that are marked as included for invoicing.

        Returns:
            account.analytic.line recordset of included timesheets only
        """
        self.ensure_one()
        included_lines = self.timesheet_line_ids.filtered(lambda t: t.included)
        return included_lines.mapped('timesheet_id')

    @api.depends('timesheet_line_ids')
    def _compute_timesheet_count(self):
        """Compute number of linked timesheets"""
        for line in self:
            line.timesheet_count = len(line.timesheet_line_ids)

    @api.depends('timesheet_line_ids.included', 'timesheet_line_ids.hours', 'timesheet_line_ids.amount')
    def _compute_totals(self):
        """Compute hours and amount from included timesheets only"""
        for line in self:
            included = line.timesheet_line_ids.filtered(lambda t: t.included)
            line.hours = sum(included.mapped('hours'))
            line.amount = sum(included.mapped('amount'))

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

    def action_exclude_zero_hour_timesheets(self):
        """Exclude all timesheet links with 0 adjusted hours from invoicing"""
        self.ensure_one()
        if self.is_readonly:
            raise UserError(_("This billing line is frozen. Cannot modify timesheets after invoice creation."))
        zero_lines = self.timesheet_line_ids.filtered(lambda t: t.hours == 0)
        if zero_lines:
            zero_lines.write({'included': False})

    def action_manage_timesheets(self):
        """Open billing line form to manage timesheet inclusion"""
        self.ensure_one()

        # Get the simplified timesheet management form view
        view_id = self.env.ref('tm_billing_control.view_tm_billing_run_line_timesheet_form').id

        return {
            'name': _('Manage Timesheets - %s') % self.display_name,
            'type': 'ir.actions.act_window',
            'res_model': 'tm.billing.run.line',
            'res_id': self.id,
            'view_mode': 'form',
            'view_id': view_id,
            'target': 'new',  # Open in dialog/modal
            'context': {
                'default_billing_run_id': self.billing_run_id.id,
            },
        }

    # ========================================================================
    # CONSTRAINTS
    # ========================================================================

    def write(self, vals):
        """Prevent modifications to billing lines after invoice creation"""
        # Check if any record is in invoiced/closed state
        for line in self:
            if line.billing_run_id.state in ('invoiced', 'closed'):
                # Allow only specific system fields to be updated
                allowed_fields = {'display_name', 'is_readonly', 'invoice_id', 'hours', 'amount', 'timesheet_count'}
                if set(vals.keys()) - allowed_fields:
                    raise UserError(_(
                        'Cannot modify billing line "%s" after invoice has been created. '
                        'Billing lines are frozen once the invoice is generated.'
                    ) % line.display_name)
        return super().write(vals)

    def unlink(self):
        """Prevent deletion of billing lines after invoice creation"""
        for line in self:
            if line.billing_run_id.state in ('invoiced', 'closed'):
                raise UserError(_(
                    'Cannot delete billing line "%s" after invoice has been created. '
                    'Billing lines are frozen once the invoice is generated.'
                ) % line.display_name)
        return super().unlink()

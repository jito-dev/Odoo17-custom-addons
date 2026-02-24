# -*- coding: utf-8 -*-

from datetime import date
from dateutil.relativedelta import relativedelta
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError


class TmBillingRun(models.Model):
    """
    Billing Run / Batch for Time & Materials Projects

    Provides controlled workflow for batch invoicing:
    1. Create billing run for (client, currency, period)
    2. Preview billing grouped by dimensions
    3. Create invoice from preview
    4. Close batch after invoice confirmation

    State workflow: draft → preview → invoiced → closed
    """

    _name = 'tm.billing.run'
    _description = 'Billing Run / Batch'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_start desc, id desc'
    _rec_names_search = ['reference', 'name']
    _check_company_auto = True

    # ========================================================================
    # FIELDS
    # ========================================================================

    # Reference / Sequence number
    reference = fields.Char(
        string='Reference',
        required=True,
        copy=False,
        readonly=True,
        index=True,
        default=lambda self: _('New'),
        help="Unique reference number for this billing run (e.g., BRN00001)",
    )

    # Computed display name
    name = fields.Char(
        string='Name',
        compute='_compute_name',
        store=True,
        readonly=True,
    )

    # Core dimensions
    active = fields.Boolean(
        string='Active',
        default=True,
        help="Deactivate to archive this billing run",
    )

    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )

    client_id = fields.Many2one(
        comodel_name='res.partner',
        string='Client',
        required=True,
        domain=[('is_company', '=', True)],
        index=True,
        help="Customer for this billing run",
    )

    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        required=True,
        default=lambda self: self.env.company.currency_id,
        help="All timesheets and invoice will use this currency",
    )

    # Date range with current month support
    use_current_month = fields.Boolean(
        string='Use Current Month',
        default=True,
        help="Automatically set period to current month (first to last day)",
    )

    date_start = fields.Date(
        string='Period Start',
        required=True,
        default=lambda self: date.today().replace(day=1),
        index=True,
        help="Start date (inclusive) for timesheet selection",
    )

    date_end = fields.Date(
        string='Period End',
        required=True,
        default=lambda self: (date.today().replace(day=1) + relativedelta(months=1, days=-1)),
        index=True,
        help="End date (inclusive) for timesheet selection",
    )

    # Grouping options
    group_by_project = fields.Boolean(
        string='Group by Project',
        default=False,
        help="If checked, billing lines will be grouped by project (separate line per project)",
    )

    group_by_month = fields.Boolean(
        string='Group by Month',
        default=False,
        help="If checked, billing lines will be split by month within the period",
    )

    # State
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('preview', 'Preview Ready'),
            ('invoiced', 'Invoiced'),
            ('closed', 'Closed'),
        ],
        string='Status',
        default='draft',
        required=True,
        readonly=True,
        tracking=True,
        index=True,
        help="Draft: editable | Preview: preview computed | Invoiced: invoice created | Closed: finalized",
    )

    # Relations
    line_ids = fields.One2many(
        comodel_name='tm.billing.run.line',
        inverse_name='billing_run_id',
        string='Billing Lines',
        help="Grouped preview lines (snapshots of billable timesheets)",
    )

    invoice_id = fields.Many2one(
        comodel_name='account.move',
        string='Invoice',
        readonly=True,
        index=True,
        help="Invoice created from this billing run",
    )

    invoice_state = fields.Selection(
        related='invoice_id.state',
        string='Invoice Status',
        store=True,
        readonly=True,
        help="Current status of the linked invoice",
    )

    invoice_payment_state = fields.Selection(
        related='invoice_id.payment_state',
        string='Payment Status',
        store=True,
        readonly=True,
        help="Payment status of the linked invoice",
    )

    # Statistics
    line_count = fields.Integer(
        string='Line Count',
        compute='_compute_stats',
        store=True,
        help="Number of billing preview lines",
    )

    total_hours = fields.Float(
        string='Total Hours',
        compute='_compute_stats',
        store=True,
        help="Total hours from all billing lines",
    )

    total_amount = fields.Monetary(
        string='Total Amount',
        currency_field='currency_id',
        compute='_compute_stats',
        store=True,
        help="Total billable amount",
    )

    timesheet_count = fields.Integer(
        string='Timesheet Count',
        compute='_compute_stats',
        store=True,
        help="Total number of timesheets included",
    )

    # Metadata
    notes = fields.Text(
        string='Notes',
        help="Internal notes about this billing run",
    )

    # ========================================================================
    # COMPUTED FIELDS
    # ========================================================================

    @api.depends('client_id', 'date_start', 'date_end', 'currency_id')
    def _compute_name(self):
        """Generate readable display name"""
        for run in self:
            parts = [
                run.client_id.name or 'No Client',
                f"{run.date_start or '?'} → {run.date_end or '?'}",
                run.currency_id.name or '',
            ]
            run.name = ' / '.join(parts)

    @api.depends('line_ids', 'line_ids.hours', 'line_ids.amount', 'line_ids.timesheet_count')
    def _compute_stats(self):
        """Compute statistics from billing lines"""
        for run in self:
            run.line_count = len(run.line_ids)
            run.total_hours = sum(run.line_ids.mapped('hours'))
            run.total_amount = sum(run.line_ids.mapped('amount'))
            run.timesheet_count = sum(run.line_ids.mapped('timesheet_count'))

    # ========================================================================
    # ONCHANGE METHODS
    # ========================================================================

    @api.onchange('use_current_month')
    def _onchange_use_current_month(self):
        """Auto-fill dates when 'Use Current Month' is checked"""
        if self.use_current_month:
            today = date.today()
            # First day of current month
            self.date_start = today.replace(day=1)
            # Last day of current month
            self.date_end = today.replace(day=1) + relativedelta(months=1, days=-1)

    # ========================================================================
    # CONSTRAINTS
    # ========================================================================

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        """Ensure date_end >= date_start"""
        for run in self:
            if run.date_end and run.date_start and run.date_end < run.date_start:
                raise ValidationError(
                    _("End date (%s) cannot be before start date (%s)") % (
                        run.date_end, run.date_start
                    )
                )

    # ========================================================================
    # CRUD OVERRIDES
    # ========================================================================

    @api.model_create_multi
    def create(self, vals_list):
        """Override create to auto-generate reference and auto-compute preview"""
        for vals in vals_list:
            if vals.get('reference', _('New')) == _('New'):
                vals['reference'] = self.env['ir.sequence'].next_by_code(
                    'tm.billing.run') or _('New')
        records = super().create(vals_list)
        for record in records:
            try:
                with self.env.cr.savepoint():
                    timesheets = record._get_billable_timesheets()
                    if timesheets:
                        record._create_preview_lines(timesheets)
            except Exception:
                pass  # Never fail billing run creation due to preview error
        return records

    def write(self, vals):
        """Enforce immutability rules based on state"""
        for run in self:
            # Prevent modification of core fields after preview
            if run.state in ('preview', 'invoiced', 'closed'):
                protected_fields = {'client_id', 'currency_id', 'date_start', 'date_end',
                                    'group_by_project', 'group_by_month', 'company_id'}
                changed_fields = set(vals.keys())
                forbidden = changed_fields & protected_fields

                if forbidden:
                    raise ValidationError(_(
                        "Cannot modify %(fields)s for billing run '%(name)s'.\n\n"
                        "This billing run is in state '%(state)s' and core fields are locked.\n"
                        "To make changes, create a new billing run."
                    ) % {
                        'fields': ', '.join(forbidden),
                        'name': run.name,
                        'state': run.state,
                    })

        return super().write(vals)

    def unlink(self):
        """Prevent deletion of invoiced/closed billing runs"""
        for run in self:
            if run.state in ('invoiced', 'closed'):
                raise ValidationError(_(
                    "Cannot delete billing run '%(name)s' in state '%(state)s'.\n\n"
                    "Invoiced or closed billing runs preserve audit trail and cannot be deleted.\n"
                    "Instead, archive the record by setting 'Active' to false."
                ) % {
                    'name': run.name,
                    'state': run.state,
                })

        return super().unlink()

    # ========================================================================
    # BUSINESS LOGIC - TIMESHEET SELECTION
    # ========================================================================

    def _get_billable_timesheets(self):
        """
        Find timesheets that meet billing criteria.

        Criteria:
        - validated = True (from timesheet_grid)
        - Not invoiced (timesheet_invoice_id = False OR state = 'cancel')
        - Has locked rate (tm_rate_card_entry_id.state IN ('locked', 'invoiced_locked'))
        - Client matches (via project.partner_id or so_line.order_id.partner_id)
        - Currency matches (via rate card entry)
        - Date within range
        - Company matches

        Note: We don't filter by timesheet_invoice_type = 'billable_time' because
        billability is determined by the Rate Card Entry, not direct SO linkage.
        Projects may not be attached to SO directly, only via Rate Card Module.

        Returns:
            account.analytic.line recordset
        """
        self.ensure_one()

        # Base domain
        domain = [
            ('validated', '=', True),
            ('project_id', '!=', False),
            ('employee_id', '!=', False),
            ('company_id', '=', self.company_id.id),
            ('date', '>=', self.date_start),
            ('date', '<=', self.date_end),

            # Not yet invoiced (standard Odoo pattern)
            '|',
                ('timesheet_invoice_id', '=', False),
                ('timesheet_invoice_id.state', '=', 'cancel'),

            # Has rate card with locked rate (this determines billability)
            ('tm_rate_card_entry_id', '!=', False),
            ('tm_rate_card_entry_id.state', 'in', ['locked', 'invoiced_locked']),
        ]

        # Search timesheets
        timesheets = self.env['account.analytic.line'].search(domain)

        # Filter by client (via project.partner_id or so_line.order_id.partner_id)
        timesheets = timesheets.filtered(
            lambda t: (t.project_id.partner_id == self.client_id) or
                      (t.so_line and t.so_line.order_id.partner_id == self.client_id)
        )

        # Filter by currency (from rate card entry)
        timesheets = timesheets.filtered(
            lambda t: t.tm_rate_card_entry_id.currency_id == self.currency_id
        )

        return timesheets

    # ========================================================================
    # BUSINESS LOGIC - GROUPING
    # ========================================================================

    def _group_timesheets_for_preview(self, timesheets):
        """
        Group timesheets by billing dimensions.

        Grouping Key: (client, currency, so_line, employee, rate, project?, month?)

        Args:
            timesheets: account.analytic.line recordset

        Returns:
            list of dicts with grouped data
        """
        self.ensure_one()

        grouped = {}

        for ts in timesheets:
            # Get SO line from rate card entry (as per user clarification #6)
            so_line = ts.tm_rate_card_entry_id.sale_order_line_id

            if not so_line:
                # Skip timesheets without SO line linkage
                continue

            # Build grouping key
            key = (
                self.client_id.id,  # client
                self.currency_id.id,  # currency
                so_line.id,  # SO line (service bucket)
                ts.employee_id.id,  # employee
                ts.tm_billing_rate,  # rate (to split mid-period changes)
                ts.project_id.id if self.group_by_project else None,  # optional project
                ts.date.strftime('%Y-%m') if self.group_by_month else None,  # optional month
            )

            if key not in grouped:
                grouped[key] = {
                    'client_id': self.client_id.id,
                    'currency_id': self.currency_id.id,
                    'sale_order_line_id': so_line.id,
                    'product_id': so_line.product_id.id,
                    'employee_id': ts.employee_id.id,
                    'rate': ts.tm_billing_rate,
                    'project_id': ts.project_id.id,  # Always store project from timesheet
                    'period_month': ts.date.strftime('%Y-%m') if self.group_by_month else False,
                    'timesheet_ids': [],
                    'hours': 0.0,
                    'amount': 0.0,
                }

            grouped[key]['timesheet_ids'].append(ts.id)
            grouped[key]['hours'] += ts.tm_adjusted_hours
            grouped[key]['amount'] += ts.tm_billable_amount

        return list(grouped.values())

    # ========================================================================
    # ACTIONS
    # ========================================================================

    def _create_preview_lines(self, timesheets):
        """
        Internal: group timesheets and create billing run lines.

        No side-effects beyond creating lines and transitioning state to 'preview'.
        Used by both action_preview() (explicit) and create() (auto-preview).

        Args:
            timesheets: account.analytic.line recordset
        """
        self.ensure_one()
        grouped_data = self._group_timesheets_for_preview(timesheets)

        BillingLine = self.env['tm.billing.run.line']
        BillingLineTimesheet = self.env['tm.billing.run.line.timesheet']

        for data in grouped_data:
            data['billing_run_id'] = self.id
            timesheet_ids = data.pop('timesheet_ids')
            data.pop('hours', None)
            data.pop('amount', None)
            line = BillingLine.create(data)
            for ts_id in timesheet_ids:
                BillingLineTimesheet.create({
                    'billing_line_id': line.id,
                    'timesheet_id': ts_id,
                    'included': True,
                })

        self.write({'state': 'preview'})

    def action_preview(self):
        """
        Compute and create billing preview lines.

        Workflow:
        1. Find billable timesheets
        2. Group by dimensions
        3. Create billing run lines
        4. Transition to 'preview' state
        """
        self.ensure_one()

        if self.state != 'draft':
            raise UserError(_("Can only preview from draft state"))

        # Find billable timesheets
        timesheets = self._get_billable_timesheets()

        if not timesheets:
            raise UserError(_(
                "No timesheets found for this billing run.\n\n"
                "Criteria:\n"
                "• Client: %(client)s\n"
                "• Currency: %(currency)s\n"
                "• Period: %(start)s to %(end)s\n"
                "• Status: Validated, Not Invoiced, With Locked Rate Card\n\n"
                "Please verify your selection criteria.\n"
                "Note: Billability is determined by Rate Card Entry, not direct SO linkage."
            ) % {
                'client': self.client_id.name,
                'currency': self.currency_id.name,
                'start': self.date_start,
                'end': self.date_end,
            })

        # Create billing lines and transition to preview
        self._create_preview_lines(timesheets)

        # Show success notification with reload
        message = _(
            'Preview computed successfully!\n\n'
            '%(line_count)s billing lines created from %(timesheet_count)s timesheets.\n'
            'Total: %(total_hours)s hours for %(total_amount)s %(currency)s'
        ) % {
            'line_count': len(self.line_ids),
            'timesheet_count': len(timesheets),
            'total_hours': self.total_hours,
            'total_amount': self.total_amount,
            'currency': self.currency_id.symbol or self.currency_id.name,
        }

        # Return notification + form reload (using standard Odoo pattern)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Billing Preview Ready'),
                'message': message,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def action_recompute(self):
        """
        Recompute preview by deleting and recreating billing lines.
        Only allowed in draft or preview state.
        """
        self.ensure_one()

        if self.state not in ('draft', 'preview'):
            raise UserError(_("Can only recompute in draft or preview state"))

        # Delete existing lines
        self.line_ids.unlink()

        # Reset to draft state
        self.write({'state': 'draft'})

        # Recompute preview
        return self.action_preview()

    def action_create_invoice(self):
        """
        Create invoice from billing run lines.

        Steps:
        1. Validate state (must be 'preview')
        2. Validate all timesheets still unbilled
        3. Create account.move (invoice)
        4. Create invoice lines from billing_run_line records
        5. Link invoice lines to correct so_line
        6. Set timesheet_invoice_id on all timesheets
        7. Mark rate cards as invoiced_locked
        8. Update billing run state to 'invoiced'
        """
        self.ensure_one()

        if self.state != 'preview':
            raise UserError(_("Can only create invoice from preview state"))

        if not self.line_ids:
            raise UserError(_("No billing lines to invoice"))

        # Get only included timesheets (excluded timesheets should not be invoiced)
        included_timesheets = self.env['account.analytic.line']
        for line in self.line_ids:
            included_timesheets |= line.get_included_timesheets()

        if not included_timesheets:
            raise UserError(_(
                "No included timesheets to invoice.\n\n"
                "All timesheets in this billing run have been excluded.\n"
                "Please include at least some timesheets before creating an invoice."
            ))

        # Validate included timesheets are still unbilled
        already_invoiced = included_timesheets.filtered(
            lambda t: t.timesheet_invoice_id and t.timesheet_invoice_id.state != 'cancel'
        )
        if already_invoiced:
            raise UserError(_(
                "Some included timesheets have already been invoiced.\n\n"
                "%(count)s timesheets are linked to existing invoices.\n"
                "Please exclude these timesheets or recompute the preview."
            ) % {'count': len(already_invoiced)})

        # Create invoice
        invoice_vals = {
            'move_type': 'out_invoice',
            'partner_id': self.client_id.id,
            'currency_id': self.currency_id.id,
            'company_id': self.company_id.id,
            'invoice_date': fields.Date.today(),
            'invoice_origin': self.reference,
            'narration': f"Billing Run: {self.reference}\nPeriod: {self.date_start} to {self.date_end}",
            'invoice_line_ids': [],
        }

        # Create invoice lines from billing run lines
        for line in self.line_ids:
            # Build invoice line description: "Product - Employee - Project - Period"
            description_parts = [line.product_id.name]
            if line.employee_id:
                description_parts.append(line.employee_id.name)
            if line.project_id:
                description_parts.append(line.project_id.name)  # Just project name, no "Project:" prefix
            if line.period_month:
                description_parts.append(f"Period: {line.period_month}")

            invoice_line_vals = {
                'name': ' - '.join(description_parts),
                'product_id': line.product_id.id,
                'quantity': line.hours,
                'price_unit': line.rate,
                'product_uom_id': self.env.ref('uom.product_uom_hour').id,
                'sale_line_ids': [(6, 0, [line.sale_order_line_id.id])],  # Link to SO line
            }
            invoice_vals['invoice_line_ids'].append((0, 0, invoice_line_vals))

        # Create invoice
        invoice = self.env['account.move'].create(invoice_vals)

        # Link ONLY INCLUDED timesheets to invoice (using standard Odoo pattern)
        # Excluded timesheets remain unlinked and available for future billing runs
        included_timesheets.write({'timesheet_invoice_id': invoice.id})

        # Mark rate cards as invoiced_locked (only for included timesheets)
        rate_cards = included_timesheets.mapped('tm_rate_card_entry_id').filtered(
            lambda r: r.state != 'invoiced_locked'
        )
        if rate_cards:
            rate_cards.action_invoiced_lock()

        # Update billing run
        self.write({
            'invoice_id': invoice.id,
            'state': 'invoiced',
        })

        # Return action to open the created invoice
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': invoice.id,
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_move_type': 'out_invoice',
            },
        }

    def action_open_invoice(self):
        """Open created invoice"""
        self.ensure_one()

        if not self.invoice_id:
            raise UserError(_("No invoice has been created yet"))

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': self.invoice_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_close(self):
        """
        Close billing run (finalize).
        Only allowed after invoice is confirmed.
        """
        self.ensure_one()

        if self.state != 'invoiced':
            raise UserError(_("Can only close billing run after invoice is created"))

        if self.invoice_id.state == 'draft':
            raise UserError(_(
                "Cannot close billing run while invoice is still in draft state.\n\n"
                "Please post the invoice first."
            ))

        self.write({'state': 'closed'})

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Billing Run Closed'),
                'message': _('Billing run %(reference)s has been finalized.') % {
                    'reference': self.reference,
                },
                'type': 'success',
                'sticky': False,
            }
        }

    def action_export_timesheets(self):
        """
        Open wizard to export timesheets to Excel/CSV
        """
        self.ensure_one()

        # Validate state (only preview, invoiced, closed)
        if self.state not in ('preview', 'invoiced', 'closed'):
            raise UserError(_(
                "Export is only available in preview, invoiced, or closed states.\n\n"
                "Please compute preview first."
            ))

        # Validate billing lines exist
        if not self.line_ids:
            raise UserError(_(
                "No billing lines to export.\n\n"
                "This billing run has no data to export."
            ))

        # Create wizard
        wizard = self.env['tm.billing.run.export.wizard'].create({
            'billing_run_id': self.id,
        })

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'tm.billing.run.export.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

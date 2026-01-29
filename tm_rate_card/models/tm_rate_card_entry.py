# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.osv import expression


class TmRateCardEntry(models.Model):
    """
    Time & Materials Rate Card Entry

    Single source of truth for T&M pricing. Each entry defines a billable rate
    for a specific combination of dimensions (company, client, service product,
    employee, optional project) within an effective date range.

    Governance:
    - draft: Fully editable
    - locked: Used by validated timesheets, pricing fields immutable
    - invoiced_locked: Used by invoices, fully immutable except notes
    """

    _name = 'tm.rate.card.entry'
    _description = 'Time & Materials Rate Card Entry'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'company_id, client_id, date_start desc, id'
    _rec_names_search = ['reference', 'name']
    _check_company_auto = True  # Automatic multi-company validation

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
        help="Unique reference number for this rate card entry (e.g., RCE00001)",
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
        help="Deactivate to hide from searches. Cannot deactivate locked/invoiced entries - set date_end instead.",
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
        compute='_compute_client_id',
        store=True,
        readonly=True,
        index=True,
        help="Customer from the selected Sales Order",
    )

    service_product_id = fields.Many2one(
        comodel_name='product.product',
        string='Service Product',
        compute='_compute_service_product_id',
        store=True,
        readonly=True,
        index=True,
        help="Service product from the selected Sales Order Line",
    )

    employee_id = fields.Many2one(
        comodel_name='hr.employee',
        string='Employee',
        required=True,
        index=True,
        help="Employee to whom this rate applies",
    )

    project_id = fields.Many2one(
        comodel_name='project.project',
        string='Specific Project',
        index=True,
        help="Optional: If set, this rate applies only to this specific project. "
             "If blank, this is a client-wide rate. Project-specific rates take priority.",
    )

    # Sales Order integration
    sale_order_id = fields.Many2one(
        comodel_name='sale.order',
        string='Sales Order',
        required=True,
        index=True,
        help="Sales Order that authorizes this rate. Client is automatically taken from the Sales Order.",
    )

    sale_order_line_id = fields.Many2one(
        comodel_name='sale.order.line',
        string='Sales Order Line',
        index=True,
        help="Sales Order Line that defines the service and pricing for this rate card entry.",
    )

    # Pricing
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        required=True,
        default=lambda self: self.env.company.currency_id,
    )

    rate = fields.Monetary(
        string='Rate',
        currency_field='currency_id',
        required=True,
        digits=(16, 2),
        help="Billable rate for this combination",
    )

    # Effective dating (inclusive ranges) - both optional for maximum flexibility
    date_start = fields.Date(
        string='Valid From',
        index=True,
        help="Start date (inclusive) when this rate becomes effective. "
             "Leave blank for indefinite past (valid from beginning of time).",
    )

    date_end = fields.Date(
        string='Valid Until',
        index=True,
        help="End date (inclusive) when this rate expires. "
             "Leave blank for indefinite future (valid forever onwards).",
    )

    # Governance / State management
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('locked', 'Locked (Used by Timesheets)'),
            ('invoiced_locked', 'Invoiced (Immutable)'),
        ],
        string='Status',
        default='draft',
        required=True,
        readonly=True,
        tracking=True,
        index=True,
        help="Draft: editable | Locked: used by validated timesheets | Invoiced: fully immutable",
    )

    locked_at = fields.Datetime(
        string='Locked At',
        readonly=True,
        help="When this entry was locked (used by validated timesheets)",
    )

    locked_by = fields.Many2one(
        comodel_name='res.users',
        string='Locked By',
        readonly=True,
        help="User who locked this entry",
    )

    invoiced_locked_at = fields.Datetime(
        string='Invoiced At',
        readonly=True,
        help="When this entry was marked as invoiced (immutable)",
    )

    invoiced_locked_by = fields.Many2one(
        comodel_name='res.users',
        string='Invoiced By',
        readonly=True,
        help="User who marked this entry as invoiced",
    )

    # Metadata
    notes = fields.Text(
        string='Notes',
        help="Internal notes about this rate card entry",
    )

    # Timesheet tracking
    timesheet_ids = fields.One2many(
        comodel_name='account.analytic.line',
        inverse_name='tm_rate_card_entry_id',
        string='Timesheets',
        domain=[('validated', '=', True)],
        help="Validated timesheet entries that used this rate card entry for billing",
    )

    timesheet_count = fields.Integer(
        string='Timesheet Count',
        compute='_compute_timesheet_stats',
        store=True,
        help="Number of timesheet entries using this rate card",
    )

    timesheet_hours = fields.Float(
        string='Total Hours',
        compute='_compute_timesheet_stats',
        store=True,
        help="Total hours tracked on timesheets using this rate card",
    )

    timesheet_amount = fields.Monetary(
        string='Total Billable Amount',
        currency_field='currency_id',
        compute='_compute_timesheet_stats',
        store=True,
        help="Total billable amount from all timesheets (hours × rate)",
    )

    # Draft timesheet preview (matching but not yet validated)
    draft_matching_timesheet_ids = fields.Many2many(
        comodel_name='account.analytic.line',
        string='Draft Matching Timesheets',
        compute='_compute_draft_matching_timesheets',
        help="Draft (unvalidated) timesheets that match this rate card entry and will use it when validated",
    )

    draft_timesheet_count = fields.Integer(
        string='Draft Timesheet Count',
        compute='_compute_draft_matching_timesheets',
        help="Number of draft timesheet entries that match this rate card",
    )

    draft_timesheet_hours = fields.Float(
        string='Draft Total Hours',
        compute='_compute_draft_matching_timesheets',
        help="Total hours from draft timesheets that match this rate card",
    )

    draft_timesheet_amount = fields.Monetary(
        string='Draft Estimated Amount',
        currency_field='currency_id',
        compute='_compute_draft_matching_timesheets',
        help="Estimated billable amount from draft timesheets (hours × rate)",
    )

    # ========================================================================
    # COMPUTED FIELDS
    # ========================================================================

    @api.depends('sale_order_id', 'sale_order_id.partner_id')
    def _compute_client_id(self):
        """Compute client from the selected Sales Order"""
        for entry in self:
            if entry.sale_order_id and entry.sale_order_id.partner_id:
                entry.client_id = entry.sale_order_id.partner_id
            else:
                entry.client_id = False

    @api.depends('sale_order_line_id', 'sale_order_line_id.product_id')
    def _compute_service_product_id(self):
        """Compute service product from the selected Sales Order Line"""
        for entry in self:
            if entry.sale_order_line_id and entry.sale_order_line_id.product_id:
                entry.service_product_id = entry.sale_order_line_id.product_id
            else:
                entry.service_product_id = False

    @api.depends('client_id', 'service_product_id', 'employee_id', 'project_id', 'sale_order_line_id', 'date_start', 'date_end')
    def _compute_name(self):
        """Generate a readable display name"""
        for entry in self:
            parts = [
                entry.client_id.name or '',
                entry.project_id.name or '(Client-wide)',
                entry.service_product_id.name or '',
                entry.employee_id.name or '',
            ]

            # Add SO line reference if linked
            if entry.sale_order_line_id:
                so_ref = f"SO: {entry.sale_order_id.name}"
                parts.insert(2, so_ref)

            # Build date range string (supports all combinations)
            if not entry.date_start and not entry.date_end:
                date_range = "∞ ↔ ∞ (all time)"
            elif entry.date_start and not entry.date_end:
                date_range = f"{entry.date_start} → ∞"
            elif not entry.date_start and entry.date_end:
                date_range = f"∞ → {entry.date_end}"
            else:
                date_range = f"{entry.date_start} → {entry.date_end}"

            entry.name = f"{' / '.join(parts)} [{date_range}]"

    @api.depends('timesheet_ids', 'timesheet_ids.unit_amount', 'timesheet_ids.tm_billable_amount')
    def _compute_timesheet_stats(self):
        """Compute statistics from related timesheets"""
        for entry in self:
            timesheets = entry.timesheet_ids
            entry.timesheet_count = len(timesheets)
            entry.timesheet_hours = sum(timesheets.mapped('unit_amount'))
            entry.timesheet_amount = sum(timesheets.mapped('tm_billable_amount'))

    def _compute_draft_matching_timesheets(self):
        """
        Find draft (unvalidated) timesheets that match this rate card entry.
        This provides a preview of what will be linked when validated.
        """
        for entry in self:
            if not entry.active or not entry.employee_id or not entry.client_id:
                # Skip if entry is incomplete or inactive
                entry.draft_matching_timesheet_ids = False
                entry.draft_timesheet_count = 0
                entry.draft_timesheet_hours = 0.0
                entry.draft_timesheet_amount = 0.0
                continue

            # Build domain to find matching draft timesheets
            domain = [
                ('validated', '=', False),  # Only draft timesheets
                ('employee_id', '=', entry.employee_id.id),  # Same employee
                ('company_id', '=', entry.company_id.id),  # Same company
                ('project_id', '!=', False),  # Must have project
            ]

            # Match project: either specific project or client-wide
            if entry.project_id:
                # Project-specific rate card: only match this project
                domain.append(('project_id', '=', entry.project_id.id))
            else:
                # Client-wide rate card: match any project for this client
                # Need to find projects belonging to this client
                client_projects = self.env['project.project'].search([
                    ('partner_id', '=', entry.client_id.id)
                ])
                if client_projects:
                    domain.append(('project_id', 'in', client_projects.ids))
                else:
                    # No projects for this client, no matches
                    entry.draft_matching_timesheet_ids = False
                    entry.draft_timesheet_count = 0
                    entry.draft_timesheet_hours = 0.0
                    entry.draft_timesheet_amount = 0.0
                    continue

            # Date range filtering
            if entry.date_start:
                domain.append(('date', '>=', entry.date_start))
            if entry.date_end:
                domain.append(('date', '<=', entry.date_end))

            # Search for matching timesheets
            matching_timesheets = self.env['account.analytic.line'].search(domain)

            # Filter by client (since project might be set but we need to verify client matches)
            # This handles cases where project partner might not match the RCE client
            matching_timesheets = matching_timesheets.filtered(
                lambda ts: (ts.project_id.partner_id == entry.client_id)
            )

            # Set results
            entry.draft_matching_timesheet_ids = matching_timesheets
            entry.draft_timesheet_count = len(matching_timesheets)
            entry.draft_timesheet_hours = sum(matching_timesheets.mapped('unit_amount'))
            # Calculate estimated amount (hours × this rate card's rate)
            entry.draft_timesheet_amount = entry.draft_timesheet_hours * entry.rate

    # ========================================================================
    # ONCHANGE METHODS
    # ========================================================================

    @api.onchange('sale_order_line_id')
    def _onchange_sale_order_line_id(self):
        """Auto-populate fields when SO line is selected"""
        if self.sale_order_line_id:
            # Auto-fill sale_order_id
            self.sale_order_id = self.sale_order_line_id.order_id

            # Auto-fill currency from SO
            if not self.currency_id or self.currency_id != self.sale_order_line_id.currency_id:
                self.currency_id = self.sale_order_line_id.currency_id

    @api.onchange('sale_order_id')
    def _onchange_sale_order_id(self):
        """Clear SO line if SO changes"""
        if self.sale_order_line_id and self.sale_order_line_id.order_id != self.sale_order_id:
            self.sale_order_line_id = False

    # ========================================================================
    # CONSTRAINTS
    # ========================================================================

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        """Ensure date_end >= date_start if both are set"""
        for entry in self:
            if entry.date_end and entry.date_start and entry.date_end < entry.date_start:
                raise ValidationError(
                    _("End date (%s) cannot be before start date (%s)") % (
                        entry.date_end, entry.date_start
                    )
                )

    @api.constrains('sale_order_id', 'sale_order_line_id', 'client_id', 'service_product_id')
    def _check_required_fields(self):
        """Ensure sales order, sales order line, client, and service product are set"""
        for entry in self:
            if not entry.sale_order_id:
                raise ValidationError(
                    _("Sales Order is required. Please select a sales order for this rate card entry.")
                )
            if not entry.sale_order_line_id:
                raise ValidationError(
                    _("Sales Order Line is required. Please select a sales order line for this rate card entry.")
                )
            if not entry.client_id:
                raise ValidationError(
                    _("Client is required. It should be automatically filled from the Sales Order. "
                      "Please ensure the selected Sales Order has a customer.")
                )
            if not entry.service_product_id:
                raise ValidationError(
                    _("Service Product is required. It should be automatically filled from the Sales Order Line. "
                      "Please ensure the selected Sales Order Line has a product.")
                )

    @api.constrains('company_id', 'client_id', 'service_product_id', 'employee_id',
                    'currency_id', 'project_id', 'sale_order_line_id', 'date_start', 'date_end', 'active')
    def _check_no_overlap(self):
        """
        Prevent overlapping date ranges for the same unique combination.

        Unique combination = (company, client, service_product, employee, currency, project, sale_order_line)
        where project_id=False and sale_order_line_id=False are treated as distinct values.

        Only active entries are checked to allow soft deletion without conflicts.

        Reference: odoo17_enterprise/odoo/addons/hr_contract/models/hr_contract.py:125-154
        """
        for entry in self.filtered('active'):
            # Base domain for same unique combination (excluding self)
            domain = [
                ('id', '!=', entry.id),
                ('active', '=', True),
                ('company_id', '=', entry.company_id.id),
                ('client_id', '=', entry.client_id.id),
                ('service_product_id', '=', entry.service_product_id.id),
                ('employee_id', '=', entry.employee_id.id),
                ('currency_id', '=', entry.currency_id.id),
            ]

            # Handle project_id (None/False is a valid distinct value)
            if entry.project_id:
                domain.append(('project_id', '=', entry.project_id.id))
            else:
                domain.append(('project_id', '=', False))

            # Handle sale_order_line_id (None/False is a valid distinct value)
            if entry.sale_order_line_id:
                domain.append(('sale_order_line_id', '=', entry.sale_order_line_id.id))
            else:
                domain.append(('sale_order_line_id', '=', False))

            # Date range overlap logic (inclusive)
            # Supports all combinations: Set+Set, Set+NULL, NULL+Set, NULL+NULL
            # NULL means indefinite (past or future)

            if not entry.date_start and not entry.date_end:
                # Case 1: NULL+NULL (indefinite both ways) - overlaps with everything
                date_domain = []  # No date restriction = matches all

            elif entry.date_start and not entry.date_end:
                # Case 2: Set+NULL (valid from date_start to ∞)
                # Overlaps if: other_end >= our_start OR other_end is NULL
                date_domain = [
                    '|',
                        ('date_end', '>=', entry.date_start),
                        ('date_end', '=', False),
                ]

            elif not entry.date_start and entry.date_end:
                # Case 3: NULL+Set (valid from -∞ to date_end)
                # Overlaps if: other_start <= our_end OR other_start is NULL
                date_domain = [
                    '|',
                        ('date_start', '<=', entry.date_end),
                        ('date_start', '=', False),
                ]

            else:
                # Case 4: Set+Set (valid from date_start to date_end)
                # Overlaps if: (other_start <= our_end OR other_start NULL)
                #          AND (other_end >= our_start OR other_end NULL)
                date_domain = [
                    '|',
                        ('date_start', '<=', entry.date_end),
                        ('date_start', '=', False),
                    '|',
                        ('date_end', '>=', entry.date_start),
                        ('date_end', '=', False),
                ]

            # Combine domains
            domain = expression.AND([domain, date_domain])

            # Check for overlaps
            if self.search_count(domain) > 0:
                project_label = entry.project_id.name if entry.project_id else '(Client-wide)'
                date_start_label = entry.date_start if entry.date_start else 'indefinite past'
                date_end_label = entry.date_end if entry.date_end else 'indefinite future'

                raise ValidationError(_(
                    "Overlapping rate card entry detected!\n\n"
                    "Combination:\n"
                    "  • Client: %(client)s\n"
                    "  • Project: %(project)s\n"
                    "  • Service: %(service)s\n"
                    "  • Employee: %(employee)s\n"
                    "  • Currency: %(currency)s\n"
                    "  • Date range: %(start)s to %(end)s\n\n"
                    "Another active entry already exists for this combination with overlapping dates."
                ) % {
                    'client': entry.client_id.name,
                    'project': project_label,
                    'service': entry.service_product_id.name,
                    'employee': entry.employee_id.name,
                    'currency': entry.currency_id.name,
                    'start': date_start_label,
                    'end': date_end_label,
                })

    # ========================================================================
    # CRUD OVERRIDES - GOVERNANCE ENFORCEMENT
    # ========================================================================

    # Fields that affect pricing logic and cannot be changed after locking
    PRICING_CRITICAL_FIELDS = {
        'company_id', 'client_id', 'service_product_id', 'employee_id',
        'currency_id', 'rate', 'date_start', 'date_end', 'project_id',
        'sale_order_id', 'sale_order_line_id'
    }

    @api.model_create_multi
    def create(self, vals_list):
        """
        Override create to auto-generate reference sequence.

        Reference: odoo17_enterprise/odoo/addons/sale/models/sale_order.py:788-799
        """
        for vals in vals_list:
            if vals.get('reference', _('New')) == _('New'):
                vals['reference'] = self.env['ir.sequence'].next_by_code(
                    'tm.rate.card.entry') or _('New')
        return super().create(vals_list)

    def write(self, vals):
        """
        Enforce immutability rules based on state.

        - locked: Cannot change pricing-critical fields, EXCEPT date_end can be set if currently NULL
        - invoiced_locked: Cannot change anything except notes
        - Cannot deactivate locked/invoiced entries (must set date_end instead)

        Reference: odoo17_enterprise/odoo/addons/hr_contract/models/hr_contract.py:295-332
        """
        for entry in self:
            changed_fields = set(vals.keys())

            # Check state-based immutability
            if entry.state == 'locked':
                # Locked: block changes to pricing-critical fields
                forbidden = changed_fields & self.PRICING_CRITICAL_FIELDS

                # Special case: allow setting date_end if it was previously NULL
                # This allows users to set expiration dates on rate cards that were
                # initially created without an end date, even after they've been locked.
                # However, once set, date_end becomes immutable like other fields.
                if 'date_end' in forbidden and not entry.date_end:
                    forbidden = forbidden - {'date_end'}

                if forbidden:
                    raise ValidationError(_(
                        "Cannot modify %(fields)s for '%(name)s'.\n\n"
                        "This entry is LOCKED because it has been used by validated timesheets.\n"
                        "Pricing-critical fields cannot be changed to maintain historical accuracy.\n\n"
                        "If you need to change rates, create a new entry with a future date_start."
                    ) % {
                        'fields': ', '.join(forbidden),
                        'name': entry.name,
                    })

            elif entry.state == 'invoiced_locked':
                # Invoiced: only notes can be changed
                allowed = {'notes'}
                forbidden = changed_fields - allowed
                if forbidden:
                    raise ValidationError(_(
                        "Cannot modify %(fields)s for '%(name)s'.\n\n"
                        "This entry is INVOICED and fully immutable.\n"
                        "Only 'Notes' can be edited to maintain invoice integrity.\n\n"
                        "Retroactive changes are not allowed."
                    ) % {
                        'fields': ', '.join(forbidden),
                        'name': entry.name,
                    })

            # Check deactivation rules
            if 'active' in vals and not vals['active']:
                if entry.state in ('locked', 'invoiced_locked'):
                    raise ValidationError(_(
                        "Cannot deactivate '%(name)s' in state '%(state)s'.\n\n"
                        "Deactivating locked or invoiced entries would hide historical references.\n\n"
                        "Instead: Set the 'Valid Until' (date_end) field to a past date "
                        "to prevent future use while preserving history."
                    ) % {
                        'name': entry.name,
                        'state': entry.state,
                    })

        return super().write(vals)

    # ========================================================================
    # PUBLIC API - RATE RESOLUTION SERVICE
    # ========================================================================

    @api.model
    def resolve_rate_for_timesheet(self, company, client, employee, date, project=None):
        """
        Simplified rate resolution for timesheets (no service product required).

        Matches based on: company, client, employee, date, project (optional)

        Matching Priority:
        1. Project-specific match (if project provided and matching entry exists)
        2. Client-wide match (project_id = False)

        Args:
            company: res.company recordset (singleton)
            client: res.partner recordset (singleton)
            employee: hr.employee recordset (singleton)
            date: date object (the date to check rate for)
            project: project.project recordset (singleton) or None

        Returns:
            tm.rate.card.entry recordset (singleton)

        Raises:
            ValidationError: If no match found or multiple matches
        """
        # Ensure singleton inputs
        company.ensure_one()
        client.ensure_one()
        employee.ensure_one()
        if project:
            project.ensure_one()

        # Base domain for matching (dimensions + date range)
        # Note: No service_product requirement - simplified matching
        base_domain = [
            ('active', '=', True),
            ('company_id', '=', company.id),
            ('client_id', '=', client.id),
            ('employee_id', '=', employee.id),
            '|',
                ('date_start', '<=', date),
                ('date_start', '=', False),
            '|',
                ('date_end', '>=', date),
                ('date_end', '=', False),
        ]

        # Try project-specific match first (higher priority)
        if project:
            project_domain = expression.AND([
                base_domain,
                [('project_id', '=', project.id)]
            ])
            entries = self.search(project_domain, limit=2)

            if len(entries) > 1:
                raise ValidationError(_(
                    "Multiple rate cards match for this timesheet!\n\n"
                    "Project: %(project)s\n"
                    "Client: %(client)s\n"
                    "Employee: %(employee)s\n"
                    "Date: %(date)s\n\n"
                    "Please ensure only one active rate card exists for this combination."
                ) % {
                    'project': project.name,
                    'client': client.name,
                    'employee': employee.name,
                    'date': date,
                })

            if entries:
                return entries

        # Fall back to client-wide match (project_id = False)
        client_domain = expression.AND([
            base_domain,
            [('project_id', '=', False)]
        ])
        entries = self.search(client_domain, limit=2)

        if len(entries) > 1:
            raise ValidationError(_(
                "Multiple rate cards match for this timesheet!\n\n"
                "Client: %(client)s\n"
                "Employee: %(employee)s\n"
                "Date: %(date)s\n\n"
                "Please ensure only one active rate card exists for this combination."
            ) % {
                'client': client.name,
                'employee': employee.name,
                'date': date,
            })

        if not entries:
            project_label = project.name if project else '(client-wide)'
            raise ValidationError(_(
                "No matching rate card found for this timesheet!\n\n"
                "Client: %(client)s\n"
                "Project: %(project)s\n"
                "Employee: %(employee)s\n"
                "Date: %(date)s\n\n"
                "Please create a rate card for this combination."
            ) % {
                'client': client.name,
                'project': project_label,
                'employee': employee.name,
                'date': date,
            })

        return entries

    @api.model
    def resolve_rate(self, company, client, service_product, employee, currency, date, project=None):
        """
        Resolve the applicable rate card entry deterministically.

        Matching Priority:
        1. Project-specific match (if project provided and matching entry exists)
        2. Client-wide match (project_id = False)

        Args:
            company: res.company recordset (singleton)
            client: res.partner recordset (singleton)
            service_product: product.product recordset (singleton)
            employee: hr.employee recordset (singleton)
            currency: res.currency recordset (singleton)
            date: date object (the date to check rate for)
            project: project.project recordset (singleton) or None

        Returns:
            tm.rate.card.entry recordset (singleton)

        Raises:
            ValidationError: If no match found or multiple matches (data integrity error)

        Reference: odoo17_enterprise/odoo/addons/product/models/product_pricelist.py:169-266
        """
        # Ensure singleton inputs
        company.ensure_one()
        client.ensure_one()
        service_product.ensure_one()
        employee.ensure_one()
        currency.ensure_one()
        if project:
            project.ensure_one()

        # Base domain for matching (dimensions + date range)
        # Date logic: rate is valid if (date_start <= date OR date_start is NULL)
        #                           AND (date_end >= date OR date_end is NULL)
        base_domain = [
            ('active', '=', True),
            ('company_id', '=', company.id),
            ('client_id', '=', client.id),
            ('service_product_id', '=', service_product.id),
            ('employee_id', '=', employee.id),
            ('currency_id', '=', currency.id),
            '|',
                ('date_start', '<=', date),
                ('date_start', '=', False),
            '|',
                ('date_end', '>=', date),
                ('date_end', '=', False),
        ]

        # Try project-specific match first (higher priority)
        if project:
            project_domain = expression.AND([
                base_domain,
                [('project_id', '=', project.id)]
            ])
            entries = self.search(project_domain, limit=2)

            if len(entries) > 1:
                # Data integrity error: constraints should prevent this
                raise ValidationError(_(
                    "Data integrity error: Multiple project-specific rate cards match!\n\n"
                    "Project: %(project)s\n"
                    "Client: %(client)s\n"
                    "Service: %(service)s\n"
                    "Employee: %(employee)s\n"
                    "Date: %(date)s\n\n"
                    "Please contact system administrator to resolve overlapping entries."
                ) % {
                    'project': project.name,
                    'client': client.name,
                    'service': service_product.name,
                    'employee': employee.name,
                    'date': date,
                })

            if entries:
                # Found project-specific match
                return entries

        # Fall back to client-wide match (project_id = False)
        client_domain = expression.AND([
            base_domain,
            [('project_id', '=', False)]
        ])
        entries = self.search(client_domain, limit=2)

        if len(entries) > 1:
            # Data integrity error: constraints should prevent this
            raise ValidationError(_(
                "Data integrity error: Multiple client-wide rate cards match!\n\n"
                "Client: %(client)s\n"
                "Service: %(service)s\n"
                "Employee: %(employee)s\n"
                "Date: %(date)s\n\n"
                "Please contact system administrator to resolve overlapping entries."
            ) % {
                'client': client.name,
                'service': service_product.name,
                'employee': employee.name,
                'date': date,
            })

        if not entries:
            # No match found
            project_label = project.name if project else '(any project)'
            raise ValidationError(_(
                "No matching rate card entry found!\n\n"
                "Client: %(client)s\n"
                "Project: %(project)s\n"
                "Service: %(service)s\n"
                "Employee: %(employee)s\n"
                "Currency: %(currency)s\n"
                "Date: %(date)s\n\n"
                "Please create a rate card entry for this combination."
            ) % {
                'client': client.name,
                'project': project_label,
                'service': service_product.name,
                'employee': employee.name,
                'currency': currency.name,
                'date': date,
            })

        return entries

    @api.model
    def explain_resolution(self, company, client, service_product, employee, currency, date, project=None):
        """
        Helper method for debugging/logging rate resolution.

        Returns a dictionary explaining which rule was used or why resolution failed.
        Useful for troubleshooting and audit trails.

        Args:
            Same as resolve_rate()

        Returns:
            dict with keys:
                - success: bool
                - entry_id: int (if success)
                - rate: float (if success)
                - currency: str (if success)
                - scope: 'project-specific' or 'client-wide' (if success)
                - effective_range: str (if success)
                - error: str (if not success)
        """
        try:
            entry = self.resolve_rate(company, client, service_product, employee, currency, date, project)

            date_end_label = str(entry.date_end) if entry.date_end else 'open-ended'

            return {
                'success': True,
                'entry_id': entry.id,
                'entry_name': entry.name,
                'rate': entry.rate,
                'currency': entry.currency_id.name,
                'scope': 'project-specific' if entry.project_id else 'client-wide',
                'effective_range': f"{entry.date_start} to {date_end_label}",
                'state': entry.state,
            }
        except ValidationError as e:
            return {
                'success': False,
                'error': str(e),
            }

    # ========================================================================
    # PUBLIC API - STATE TRANSITIONS (For Future Module Integration)
    # ========================================================================

    def action_lock(self):
        """
        Lock this entry (mark as used by validated timesheets).

        Called by future timesheet validation module when timesheets using
        this rate card are validated.

        Transitions: draft → locked
        """
        for entry in self:
            if entry.state != 'draft':
                raise ValidationError(_(
                    "Cannot lock '%(name)s' - only draft entries can be locked.\n"
                    "Current state: %(state)s"
                ) % {
                    'name': entry.name,
                    'state': entry.state,
                })

            entry.write({
                'state': 'locked',
                'locked_at': fields.Datetime.now(),
                'locked_by': self.env.user.id,
            })

    def action_invoiced_lock(self):
        """
        Mark this entry as invoiced (fully immutable).

        Called by future invoicing module when invoices using this rate card
        are created/confirmed.

        Transitions: draft/locked → invoiced_locked
        """
        for entry in self:
            if entry.state == 'invoiced_locked':
                # Already invoiced, skip silently
                continue

            if entry.state not in ('draft', 'locked'):
                raise ValidationError(_(
                    "Cannot mark '%(name)s' as invoiced - invalid state.\n"
                    "Current state: %(state)s"
                ) % {
                    'name': entry.name,
                    'state': entry.state,
                })

            entry.write({
                'state': 'invoiced_locked',
                'invoiced_locked_at': fields.Datetime.now(),
                'invoiced_locked_by': self.env.user.id,
            })

    def action_unlock(self):
        """
        Unlock this entry (admin override - use with caution).

        Allows unlocking from 'locked' back to 'draft' for corrections.
        Cannot unlock 'invoiced_locked' entries to preserve invoice integrity.

        Transitions: locked → draft
        """
        for entry in self:
            if entry.state == 'invoiced_locked':
                raise ValidationError(_(
                    "Cannot unlock '%(name)s' - invoiced entries are permanently immutable.\n\n"
                    "Unlocking invoiced entries would compromise invoice integrity and audit trail."
                ) % {'name': entry.name})

            if entry.state == 'draft':
                # Already draft, skip silently
                continue

            entry.write({
                'state': 'draft',
                'locked_at': False,
                'locked_by': False,
            })

    def action_open_draft_timesheets(self):
        """
        Open a tree view of draft timesheets that match this rate card entry.

        This action opens a filtered view of unvalidated timesheets that will
        link to this RCE when validated, allowing users to review and validate
        them directly from the RCE context.

        Returns:
            ir.actions.act_window action to open timesheet tree view
        """
        self.ensure_one()

        # Get the matching draft timesheets
        # Force recomputation to ensure we have the latest matches
        self._compute_draft_matching_timesheets()

        # Get the IDs of matching timesheets
        timesheet_ids = self.draft_matching_timesheet_ids.ids

        # Build action
        action = {
            'name': _('Draft Timesheets - %(rce_name)s') % {'rce_name': self.reference},
            'type': 'ir.actions.act_window',
            'res_model': 'account.analytic.line',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', timesheet_ids)],
            'context': {
                'default_employee_id': self.employee_id.id,
                'default_project_id': self.project_id.id if self.project_id else False,
                'search_default_validated': 0,  # Show unvalidated
                'create': False,  # Don't allow creating from this view
            },
            'target': 'current',
        }

        # Add helpful message if no matching timesheets
        if not timesheet_ids:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('No Draft Timesheets'),
                    'message': _(
                        'No draft timesheets match this rate card entry.\n\n'
                        'Matching criteria:\n'
                        '• Employee: %(employee)s\n'
                        '• Client: %(client)s\n'
                        '• Project: %(project)s\n'
                        '• Date Range: %(date_range)s'
                    ) % {
                        'employee': self.employee_id.name,
                        'client': self.client_id.name,
                        'project': self.project_id.name if self.project_id else 'Any (client-wide)',
                        'date_range': f"{self.date_start or '∞'} → {self.date_end or '∞'}",
                    },
                    'type': 'info',
                    'sticky': False,
                }
            }

        return action

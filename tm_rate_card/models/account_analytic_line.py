# -*- coding: utf-8 -*-

import logging
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.tools import float_compare

_logger = logging.getLogger(__name__)

# Tolerance used to decide whether tm_adjusted_hours still mirrors unit_amount.
# 5 decimal digits ≈ 0.04 seconds: far below the smallest meaningful adjustment
# (1 minute = 0.0167 h) and far above the float8 <-> numeric representation noise.
ADJUSTED_HOURS_SYNC_PRECISION = 5


class AccountAnalyticLine(models.Model):
    """
    Extend account.analytic.line (timesheets) to link with Rate Card Entry
    """

    _inherit = 'account.analytic.line'

    # Link to rate card entry used for this timesheet
    tm_rate_card_entry_id = fields.Many2one(
        comodel_name='tm.rate.card.entry',
        string='Rate Card Entry',
        index=True,
        help="Rate card entry that was used to determine the billing rate for this timesheet entry",
    )

    # Billing currency (from the linked Rate Card Entry, not the company currency)
    tm_billing_currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Billing Currency',
        related='tm_rate_card_entry_id.currency_id',
        store=True,
        readonly=True,
        help="Currency of the billing rate (from the linked Rate Card Entry)",
    )

    # Billing rate (can be different from cost rate)
    tm_billing_rate = fields.Monetary(
        string='Billing Rate',
        currency_field='tm_billing_currency_id',
        help="Billing rate per unit (e.g., per hour) for this timesheet entry",
    )

    # Adjusted hours for billing (editable by PM, defaults to unit_amount)
    tm_adjusted_hours = fields.Float(
        string='Adjusted Hours',
        # digits=False = NUMERIC column with no fixed precision, all significant
        # digits stored (see Float.column_type in odoo/fields.py). Required here:
        # hours typed as 0:20 / 0:40 / 1:10 are not representable in 2 decimals.
        # Do NOT pass a decimal.precision name: an unknown name silently resolves
        # to 2 digits (decimal_precision.precision_get), which truncated the value.
        # Do NOT drop the argument either: digits=None switches the column to
        # float8 and makes Odoo rewrite the existing column.
        digits=False,
        store=True,
        help="Billing hours (may differ from logged hours). Initialized to logged hours on creation. "
             "Editable by PM after timesheet validation. Read-only once invoiced.",
    )

    # Billable amount (tm_adjusted_hours * billing_rate)
    tm_billable_amount = fields.Monetary(
        string='Billable Amount',
        currency_field='tm_billing_currency_id',
        compute='_compute_tm_billable_amount',
        store=True,
        help="Total billable amount (adjusted hours × billing rate)",
    )

    @api.depends('tm_adjusted_hours', 'tm_billing_rate')
    def _compute_tm_billable_amount(self):
        """Calculate billable amount from adjusted hours and billing rate"""
        for line in self:
            line.tm_billable_amount = line.tm_adjusted_hours * line.tm_billing_rate

    def _get_rate_card_params(self):
        """
        Get parameters needed to resolve rate card for this timesheet.
        Returns dict with all required fields, or empty dict if any field is missing.

        For timesheets, we use simplified matching:
        - company, client, employee, date, project (required)
        - service_product is NOT required
        """
        self.ensure_one()

        # Check if this is a timesheet entry (has project and employee)
        if not self.project_id or not self.employee_id:
            return {}

        # Get client from project (or SO line if available). so_line always exists:
        # sale_timesheet is a declared dependency since v1.14.11.
        if self.so_line:
            client = self.so_line.order_id.partner_id
        else:
            client = self.project_id.partner_id

        # Must have client
        if not client:
            return {}

        return {
            'company': self.company_id,
            'client': client,
            'employee': self.employee_id,
            'date': self.date,
            'project': self.project_id,
        }

    def _resolve_and_set_rate_card(self, raise_on_error=False):
        """
        Find matching rate card and set billing rate for this timesheet.

        Args:
            raise_on_error: If True, raises ValidationError when rate card not found.
                           If False, silently skips.
        """
        results = {
            'linked': 0,
            'skipped_missing_fields': 0,
            'skipped_no_match': 0,
            'errors': []
        }

        for line in self:
            # Skip if already has rate card
            if line.tm_rate_card_entry_id:
                continue

            # Get parameters for rate resolution
            params = line._get_rate_card_params()
            if not params:
                # Missing required fields
                results['skipped_missing_fields'] += 1
                error_msg = _(
                    "Cannot validate timesheet on %(date)s for employee '%(employee)s'.\n\n"
                    "Missing required fields: Project, Employee, or Client.\n\n"
                    "Please ensure the timesheet has all required information before validating."
                ) % {
                    'date': line.date,
                    'employee': line.employee_id.name if line.employee_id else 'Unknown',
                }
                results['errors'].append(error_msg)
                if raise_on_error:
                    raise ValidationError(error_msg)
                continue

            try:
                # Try to find matching rate card using simplified timesheet resolution
                rate_card = self.env['tm.rate.card.entry'].resolve_rate_for_timesheet(**params)

                _logger.info("Found rate card %s (ID: %s) for timesheet %s", rate_card.reference, rate_card.id, line.id)

                # Set rate card and billing rate
                # Note: SO line is set in action_validate_timesheet() AFTER parent validation
                vals = {
                    'tm_rate_card_entry_id': rate_card.id,
                    'tm_billing_rate': rate_card.rate,
                }

                line.write(vals)
                results['linked'] += 1

            except ValidationError as e:
                # No matching rate card found
                results['skipped_no_match'] += 1
                error_msg = _(
                    "Cannot validate timesheet on %(date)s for employee '%(employee)s'.\n\n"
                    "No matching Rate Card Entry found for:\n"
                    "• Client: %(client)s\n"
                    "• Project: %(project)s\n"
                    "• Employee: %(employee)s\n"
                    "• Date: %(date)s\n\n"
                    "Please create a Rate Card Entry with these parameters before validating this timesheet.\n\n"
                    "Go to: Time & Materials → Rate Card Entries → Create"
                ) % {
                    'date': line.date,
                    'employee': line.employee_id.name if line.employee_id else 'Unknown',
                    'client': params.get('client').name if params.get('client') else 'Unknown',
                    'project': params.get('project').name if params.get('project') else 'Unknown',
                }
                results['errors'].append(error_msg)
                if raise_on_error:
                    raise ValidationError(error_msg)

        return results

    @api.model_create_multi
    def create(self, vals_list):
        """
        Create timesheets without auto-linking rate cards.
        Rate cards are ONLY linked during validation, not on creation.
        Initializes tm_adjusted_hours = unit_amount if not explicitly provided.
        """
        for vals in vals_list:
            if 'tm_adjusted_hours' not in vals:
                vals['tm_adjusted_hours'] = vals.get('unit_amount', 0.0)

        lines = super().create(vals_list)

        # REMOVED: Auto-linking on creation
        # Rate cards should only be linked when timesheet is validated
        # This ensures only validated timesheets appear in RCE views

        return lines

    def write(self, vals):
        """
        Override write to:
        1. Prevent editing tm_adjusted_hours on invoiced timesheets.
        2. Auto-sync tm_adjusted_hours with unit_amount for non-validated,
           non-manually-adjusted records (using context flag to prevent recursion).

        Rate cards are ONLY linked during validation, not on field changes.
        """
        # 1. Prevent editing tm_adjusted_hours on invoiced timesheets
        if 'tm_adjusted_hours' in vals and not self.env.context.get('_syncing_adjusted_hours'):
            for line in self:
                inv = line.timesheet_invoice_id
                if inv and inv.state != 'cancel':
                    raise ValidationError(_(
                        "Cannot modify Adjusted Hours for timesheet entry on %(date)s "
                        "(Employee: %(employee)s).\n\n"
                        "This timesheet is already invoiced (Invoice: %(invoice)s).\n"
                        "Adjusted hours are locked once the timesheet is billed."
                    ) % {
                        'date': line.date,
                        'employee': line.employee_id.name if line.employee_id else 'Unknown',
                        'invoice': inv.name,
                    })

        # 2. Auto-sync tm_adjusted_hours when unit_amount changes on non-validated,
        #    non-manually-adjusted records (context flag prevents recursion)
        if 'unit_amount' in vals and 'tm_adjusted_hours' not in vals:
            if not self.env.context.get('_syncing_adjusted_hours'):
                # Only sync records that: (a) are not yet validated, AND
                # (b) have tm_adjusted_hours still equal to unit_amount (not manually adjusted).
                # Compared with float_compare, not ==: unit_amount is float8 while
                # tm_adjusted_hours is numeric, so an exact equality test reports
                # "manually adjusted" for records nobody ever adjusted, and those
                # records then stop following unit_amount forever.
                lines_to_sync = self.filtered(
                    lambda l: not l.validated and float_compare(
                        l.tm_adjusted_hours,
                        l.unit_amount,
                        precision_digits=ADJUSTED_HOURS_SYNC_PRECISION,
                    ) == 0
                )
                result = super().write(vals)
                if lines_to_sync:
                    lines_to_sync.with_context(_syncing_adjusted_hours=True).write(
                        {'tm_adjusted_hours': vals['unit_amount']}
                    )
                return result

        # REMOVED: Auto-resolution on field changes
        # Rate cards should only be linked when timesheet is validated
        # This prevents draft timesheets from appearing in RCE views

        return super().write(vals)

    def action_validate_timesheet(self):
        """
        Override validation to REQUIRE rate card linking.

        Workflow:
        1. Link rate cards (FAILS if no matching RCE found)
        2. Call parent validation (timesheet_grid module)
        3. Set SO lines from rate cards (AFTER parent to prevent override)
        4. Auto-lock the RCE entries that are now being used

        This ensures:
        - Only validated timesheets appear in RCE views
        - Validation is rejected if no matching rate card exists
        - SO lines are correctly linked from rate cards
        - RCEs are automatically locked when timesheets use them
        """
        # CRITICAL: Link rate cards BEFORE validation
        # raise_on_error=True means validation will FAIL if no matching RCE exists
        self._resolve_and_set_rate_card(raise_on_error=True)

        # Call parent validation (timesheet_grid module)
        result = super().action_validate_timesheet() if hasattr(super(), 'action_validate_timesheet') else True

        # Set SO lines AFTER parent validation to prevent being overridden
        # The parent validation might trigger compute methods that would override our so_line
        so_lines_set = 0
        so_lines_missing = 0
        for line in self:
            if line.tm_rate_card_entry_id:
                if line.tm_rate_card_entry_id.sale_order_line_id:
                    _logger.info("Setting SO line %s on validated timesheet %s from rate card %s",
                                line.tm_rate_card_entry_id.sale_order_line_id.id, line.id,
                                line.tm_rate_card_entry_id.reference)
                    try:
                        line.sudo().write({
                            'so_line': line.tm_rate_card_entry_id.sale_order_line_id.id,
                            'is_so_line_edited': True,
                        })
                        so_lines_set += 1
                        _logger.info("Successfully set SO line. Timesheet %s now has so_line: %s",
                                    line.id, line.so_line.id if line.so_line else 'None')
                    except Exception as e:
                        _logger.error("Failed to set SO line on timesheet %s: %s", line.id, str(e))
                        raise
                else:
                    so_lines_missing += 1
                    _logger.warning("Rate card %s (ID: %s) for timesheet %s does not have a sale_order_line_id!",
                                  line.tm_rate_card_entry_id.reference,
                                  line.tm_rate_card_entry_id.id, line.id)

        if so_lines_missing > 0:
            _logger.warning("WARNING: %d timesheet(s) validated but Rate Card Entry has no Sales Order Line set!",
                          so_lines_missing)

        # Auto-lock the rate card entries that are now being used by validated timesheets
        # Only lock entries that are still in 'draft' state (don't re-lock already locked entries)
        rate_cards_to_lock = self.mapped('tm_rate_card_entry_id').filtered(lambda r: r.state == 'draft')
        if rate_cards_to_lock:
            rate_cards_to_lock.action_lock()

        # Add debug notification (temporary)
        if so_lines_set > 0 or so_lines_missing > 0:
            if isinstance(result, dict) and result.get('type') == 'ir.actions.client':
                # Append to existing notification
                result['params']['message'] += f"\n\nDEBUG: SO Lines set: {so_lines_set}, Missing: {so_lines_missing}"

        return result

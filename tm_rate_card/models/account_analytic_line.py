# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


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

    # Billing rate (can be different from cost rate)
    tm_billing_rate = fields.Monetary(
        string='Billing Rate',
        currency_field='currency_id',
        help="Billing rate per unit (e.g., per hour) for this timesheet entry",
    )

    # Billable amount (unit_amount * billing_rate)
    tm_billable_amount = fields.Monetary(
        string='Billable Amount',
        currency_field='currency_id',
        compute='_compute_tm_billable_amount',
        store=True,
        help="Total billable amount (hours × billing rate)",
    )

    @api.depends('unit_amount', 'tm_billing_rate')
    def _compute_tm_billable_amount(self):
        """Calculate billable amount from hours and billing rate"""
        for line in self:
            line.tm_billable_amount = line.unit_amount * line.tm_billing_rate

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

        # Get client from project (or SO line if available)
        if hasattr(self, 'so_line') and self.so_line:
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

                # Set rate card and billing rate
                line.write({
                    'tm_rate_card_entry_id': rate_card.id,
                    'tm_billing_rate': rate_card.rate,
                })
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
        """
        lines = super().create(vals_list)

        # REMOVED: Auto-linking on creation
        # Rate cards should only be linked when timesheet is validated
        # This ensures only validated timesheets appear in RCE views

        return lines

    def write(self, vals):
        """
        Standard write without auto-resolution.
        Rate cards are ONLY linked during validation, not on field changes.
        """
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
        3. Auto-lock the RCE entries that are now being used

        This ensures:
        - Only validated timesheets appear in RCE views
        - Validation is rejected if no matching rate card exists
        - RCEs are automatically locked when timesheets use them
        """
        # CRITICAL: Link rate cards BEFORE validation
        # raise_on_error=True means validation will FAIL if no matching RCE exists
        self._resolve_and_set_rate_card(raise_on_error=True)

        # Call parent validation (timesheet_grid module)
        result = super().action_validate_timesheet() if hasattr(super(), 'action_validate_timesheet') else True

        # Auto-lock the rate card entries that are now being used by validated timesheets
        # Only lock entries that are still in 'draft' state (don't re-lock already locked entries)
        rate_cards_to_lock = self.mapped('tm_rate_card_entry_id').filtered(lambda r: r.state == 'draft')
        if rate_cards_to_lock:
            rate_cards_to_lock.action_lock()

        return result

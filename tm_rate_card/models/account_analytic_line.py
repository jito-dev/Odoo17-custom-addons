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
                error_msg = f"Timesheet ID {line.id}: Missing required fields (project, employee, or service product)"
                results['errors'].append(error_msg)
                if raise_on_error:
                    raise ValidationError(_(error_msg))
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
                error_msg = f"Timesheet ID {line.id}: No matching rate card found - {str(e)}"
                results['errors'].append(error_msg)
                if raise_on_error:
                    raise

        return results

    @api.model_create_multi
    def create(self, vals_list):
        """Auto-link rate card when creating timesheet"""
        lines = super().create(vals_list)

        # Try to resolve rate cards for new timesheets
        lines._resolve_and_set_rate_card()

        return lines

    def write(self, vals):
        """Re-resolve rate card if key fields change"""
        # If key fields changed, mark for re-resolution
        key_fields = {'project_id', 'employee_id', 'date', 'product_id'}
        should_resolve = any(field in vals for field in key_fields)

        # Perform the write
        result = super().write(vals)

        # Re-resolve if needed (and not already setting rate card fields)
        if should_resolve and 'tm_rate_card_entry_id' not in vals:
            # Clear and re-resolve
            super(AccountAnalyticLine, self).write({
                'tm_rate_card_entry_id': False,
                'tm_billing_rate': 0.0,
            })
            self._resolve_and_set_rate_card()

        return result

    def action_validate_timesheet(self):
        """
        Override validation to auto-link rate cards when timesheets are validated.
        This hooks into the timesheet_grid module's validation workflow if installed.
        """
        # Call parent validation (if timesheet_grid module is installed)
        result = super().action_validate_timesheet() if hasattr(super(), 'action_validate_timesheet') else True

        # Auto-link rate cards for newly validated timesheets
        self._resolve_and_set_rate_card()

        return result

    def action_resolve_rate_cards(self):
        """
        Action to manually resolve rate cards for selected timesheets.
        Useful for bulk updating existing timesheets.
        """
        # Clear existing rate cards
        for line in self:
            super(AccountAnalyticLine, line).write({
                'tm_rate_card_entry_id': False,
                'tm_billing_rate': 0.0,
            })

        # Resolve and get results
        results = self._resolve_and_set_rate_card(raise_on_error=False)

        # Build message
        message = f"""
Processed {len(self)} timesheet(s):
• Linked: {results['linked']}
• Skipped (missing fields): {results['skipped_missing_fields']}
• Skipped (no rate card found): {results['skipped_no_match']}
        """.strip()

        notification_type = 'success' if results['linked'] > 0 else 'warning'

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Rate Cards Processing Complete'),
                'message': message,
                'type': notification_type,
                'sticky': True,
            }
        }

    def action_diagnose_rate_card(self):
        """
        Diagnostic action to check why timesheet can't link to rate card.
        Shows detailed information about what's missing or wrong.
        """
        self.ensure_one()

        diagnostic_info = []

        # Check basic fields
        diagnostic_info.append("=== TIMESHEET INFORMATION ===")
        diagnostic_info.append(f"Timesheet ID: {self.id}")
        diagnostic_info.append(f"Date: {self.date}")
        diagnostic_info.append(f"Hours: {self.unit_amount}")
        diagnostic_info.append("")

        diagnostic_info.append("=== REQUIRED FIELDS ===")
        diagnostic_info.append(f"✓ Project: {self.project_id.name if self.project_id else '❌ MISSING'}")
        diagnostic_info.append(f"✓ Employee: {self.employee_id.name if self.employee_id else '❌ MISSING'}")
        diagnostic_info.append(f"✓ Company: {self.company_id.name if self.company_id else '❌ MISSING'}")
        diagnostic_info.append("")

        # Check client
        diagnostic_info.append("=== CLIENT RESOLUTION ===")
        client = None
        if hasattr(self, 'so_line') and self.so_line:
            client = self.so_line.order_id.partner_id
            diagnostic_info.append(f"Source: Sales Order Line ({self.so_line.display_name})")
            diagnostic_info.append(f"✓ Client: {client.name if client else '❌ SO has no customer'}")
        else:
            client = self.project_id.partner_id if self.project_id else None
            diagnostic_info.append(f"Source: Project Partner")
            diagnostic_info.append(f"{'✓' if client else '❌'} Client: {client.name if client else 'MISSING - Project has no customer'}")
        diagnostic_info.append("")

        # Check service product (OPTIONAL - not required for matching)
        diagnostic_info.append("=== SERVICE PRODUCT (Optional) ===")
        service_product = None
        if hasattr(self, 'so_line') and self.so_line:
            service_product = self.so_line.product_id
            diagnostic_info.append(f"Source: Sales Order Line Product")
            diagnostic_info.append(f"✓ Product: {service_product.name if service_product else 'None'}")
        elif hasattr(self, 'product_id') and self.product_id:
            service_product = self.product_id
            diagnostic_info.append(f"Source: Timesheet Product Field")
            diagnostic_info.append(f"✓ Product: {service_product.name}")
        else:
            diagnostic_info.append(f"Source: None available")
            diagnostic_info.append(f"  Product: Not set (this is OK - not required for matching)")
        diagnostic_info.append("")

        # Try to find rate card
        diagnostic_info.append("=== RATE CARD SEARCH ===")
        params = self._get_rate_card_params()

        if not params:
            diagnostic_info.append("❌ Cannot search - missing required parameters")
        else:
            diagnostic_info.append("Simplified matching (no service product required):")
            diagnostic_info.append(f"  • Company: {params['company'].name}")
            diagnostic_info.append(f"  • Client: {params['client'].name}")
            diagnostic_info.append(f"  • Employee: {params['employee'].name}")
            diagnostic_info.append(f"  • Date: {params['date']}")
            diagnostic_info.append(f"  • Project: {params['project'].name if params['project'] else 'Client-wide (any project)'}")
            diagnostic_info.append("")

            try:
                rate_card = self.env['tm.rate.card.entry'].resolve_rate_for_timesheet(**params)
                diagnostic_info.append(f"✅ MATCH FOUND: {rate_card.reference} - {rate_card.name}")
                diagnostic_info.append(f"   Rate: {rate_card.rate} {rate_card.currency_id.name}")
                diagnostic_info.append(f"   Service Product: {rate_card.service_product_id.name}")
            except ValidationError as e:
                diagnostic_info.append("❌ NO MATCH FOUND")
                diagnostic_info.append(f"   Reason: {str(e)}")
                diagnostic_info.append("")
                diagnostic_info.append("=== WHAT TO DO ===")
                diagnostic_info.append("Create a rate card with these parameters:")
                diagnostic_info.append(f"  • Sales Order: (any order for client '{params['client'].name}')")
                diagnostic_info.append(f"  • Client: {params['client'].name} (auto-fills from SO)")
                diagnostic_info.append(f"  • Sales Order Line: (any line from that SO)")
                diagnostic_info.append(f"  • Service Product: (auto-fills from SO line)")
                diagnostic_info.append(f"  • Employee: {params['employee'].name}")
                diagnostic_info.append(f"  • Rate: (your billable rate, e.g., $150.00)")
                diagnostic_info.append(f"  • Valid From: {params['date']} (or earlier, or leave blank)")
                diagnostic_info.append(f"  • Valid Until: (leave blank for ongoing)")
                if params.get('project'):
                    diagnostic_info.append(f"  • Project: {params['project'].name} (for project-specific rate)")
                    diagnostic_info.append(f"    OR leave Project blank for client-wide rate")

        # Check current rate card
        diagnostic_info.append("")
        diagnostic_info.append("=== CURRENT STATUS ===")
        if self.tm_rate_card_entry_id:
            diagnostic_info.append(f"✓ Linked to: {self.tm_rate_card_entry_id.reference}")
            diagnostic_info.append(f"  Billing Rate: {self.tm_billing_rate}")
            diagnostic_info.append(f"  Billable Amount: {self.tm_billable_amount}")
        else:
            diagnostic_info.append("❌ Not linked to any rate card")

        message = "\n".join(diagnostic_info)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Rate Card Diagnostic'),
                'message': f'<pre>{message}</pre>',
                'type': 'info',
                'sticky': True,
            }
        }

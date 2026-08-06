# -*- coding: utf-8 -*-
"""Entries the wizard reports but must never convert.

Validated entries were always excluded. Invoiced ones were not, and that gap is
not cosmetic: ``action_apply`` writes ``unit_amount``, which makes ``tm_rate_card``
auto-sync ``tm_adjusted_hours`` through a context flag that bypasses its own
"locked once billed" guard. Converting an invoiced entry would therefore rewrite
billed hours silently.
"""

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import TimesheetRoundingCommon


@tagged('post_install', '-at_install')
class TestWizardBlockedEntries(TimesheetRoundingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create({'name': 'Rounding Test Customer'})

    def _new_invoice(self):
        return self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.customer.id,
        })

    def _invoiced_timesheet(self, hours):
        timesheet = self._make_off_grid([hours])
        timesheet.timesheet_invoice_id = self._new_invoice()
        return timesheet

    # -- validated -----------------------------------------------------

    def test_validated_entry_is_blocked(self):
        timesheet = self._make_off_grid([1 / 3])
        timesheet.validated = True

        line = self._open_wizard(timesheet).line_ids
        self.assertTrue(line.is_blocked)
        self.assertEqual(line.blocked_reason, "Validated")

    # -- invoiced ------------------------------------------------------

    def test_invoiced_entry_is_blocked(self):
        timesheet = self._invoiced_timesheet(1 / 3)

        line = self._open_wizard(timesheet).line_ids
        self.assertTrue(line.is_blocked)
        self.assertIn("Invoiced", line.blocked_reason)

    def test_invoiced_entry_is_reported_not_hidden(self):
        """The user has to see what was skipped, not silently lose rows."""
        timesheet = self._invoiced_timesheet(1 / 3)
        wizard = self._open_wizard(timesheet)

        self.assertEqual(len(wizard.line_ids), 1)
        self.assertEqual(wizard.blocked_count, 1)
        self.assertEqual(wizard.to_change_count, 0)

    def test_invoiced_entry_is_not_converted(self):
        timesheet = self._invoiced_timesheet(1 / 3)
        wizard = self._open_wizard(timesheet, 'up')

        with self.assertRaises(UserError):
            wizard.action_apply()

        self.assertAlmostEqual(timesheet.unit_amount, 1 / 3, places=10)

    def test_invoiced_entry_keeps_its_adjusted_hours(self):
        """The reason the guard exists: the auto-sync bypasses the billing lock."""
        timesheet = self._invoiced_timesheet(1 / 3)
        before = timesheet.tm_adjusted_hours

        other = self._make_off_grid([2 / 3])
        wizard = self._open_wizard(timesheet | other, 'up')
        wizard.action_apply()

        self.assertAlmostEqual(timesheet.tm_adjusted_hours, before, places=10)
        self.assertAlmostEqual(timesheet.unit_amount, 1 / 3, places=10)
        self.assertEqual(other.unit_amount, 0.75, "unblocked entries still convert")

    def test_cancelled_invoice_does_not_block(self):
        timesheet = self._invoiced_timesheet(1 / 3)
        timesheet.timesheet_invoice_id.button_cancel()

        line = self._open_wizard(timesheet).line_ids
        self.assertFalse(line.is_blocked)
        self.assertFalse(line.blocked_reason)

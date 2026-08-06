# -*- coding: utf-8 -*-

from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import TimesheetRoundingCommon


@tagged('post_install', '-at_install')
class TestRoundingValidation(TimesheetRoundingCommon):
    """Requirement C: validation of new and edited entries."""

    # -- 15 minute step ------------------------------------------------

    def test_step_15_accepts_multiples(self):
        self._enable_rounding('15')
        for hours in (0.25, 0.5, 0.75, 1.0, 1.25):
            entry = self._new_timesheet(hours)
            self.assertEqual(entry.unit_amount, hours)

    def test_step_15_rejects_20_minutes(self):
        self._enable_rounding('15')
        with self.assertRaises(ValidationError):
            self._new_timesheet(1 / 3)

    def test_step_15_rejects_40_minutes(self):
        self._enable_rounding('15')
        with self.assertRaises(ValidationError):
            self._new_timesheet(2 / 3)

    def test_step_15_rejects_70_minutes(self):
        self._enable_rounding('15')
        with self.assertRaises(ValidationError):
            self._new_timesheet(7 / 6)

    # -- 30 minute step ------------------------------------------------

    def test_step_30_accepts_multiples(self):
        self._enable_rounding('30')
        for hours in (0.5, 1.0, 1.5, 2.0):
            entry = self._new_timesheet(hours)
            self.assertEqual(entry.unit_amount, hours)

    def test_step_30_rejects_15_minutes(self):
        self._enable_rounding('30')
        with self.assertRaises(ValidationError):
            self._new_timesheet(0.25)

    def test_step_30_rejects_45_minutes(self):
        self._enable_rounding('30')
        with self.assertRaises(ValidationError):
            self._new_timesheet(0.75)

    # -- disabled ------------------------------------------------------

    def test_disabled_setting_allows_anything(self):
        """Requirement B.5 / test 4: current behaviour is untouched when off."""
        self._disable_rounding()
        for hours in (1 / 3, 2 / 3, 7 / 6, 0.05):
            entry = self._new_timesheet(hours)
            self.assertAlmostEqual(entry.unit_amount, hours, places=10)

    # -- writes --------------------------------------------------------

    def test_write_to_invalid_value_is_rejected(self):
        self._enable_rounding('15')
        entry = self._new_timesheet(0.5)
        with self.assertRaises(ValidationError):
            entry.unit_amount = 1 / 3

    def test_write_to_valid_value_passes(self):
        self._enable_rounding('15')
        entry = self._new_timesheet(0.5)
        entry.unit_amount = 1.25
        self.assertEqual(entry.unit_amount, 1.25)

    def test_existing_off_grid_entry_stays_editable(self):
        """Decision: validate only when the duration actually changes.

        An entry created before the setting was switched on keeps its value and
        must remain editable, otherwise a third of the database freezes.
        """
        self._disable_rounding()
        entry = self._new_timesheet(1 / 3)

        self._enable_rounding('15')
        entry.name = 'edited description'
        self.assertEqual(entry.name, 'edited description')
        self.assertAlmostEqual(entry.unit_amount, 1 / 3, places=10)

    def test_enabling_setting_does_not_touch_existing_entries(self):
        """Requirement D / test 5."""
        self._disable_rounding()
        values = (1 / 3, 2 / 3, 7 / 6)
        entries = [self._new_timesheet(hours) for hours in values]

        self._enable_rounding('15')

        for entry, expected in zip(entries, values):
            self.assertAlmostEqual(entry.unit_amount, expected, places=10)

    # -- scope ---------------------------------------------------------

    def test_non_timesheet_analytic_line_is_not_checked(self):
        """Analytic lines without a project carry quantities, not durations."""
        self._enable_rounding('15')
        line = self.env['account.analytic.line'].create({
            'name': 'plain analytic entry',
            'account_id': self.analytic_account.id,
            'unit_amount': 1 / 3,
        })
        self.assertAlmostEqual(line.unit_amount, 1 / 3, places=10)

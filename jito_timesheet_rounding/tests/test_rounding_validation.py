# -*- coding: utf-8 -*-

from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import TimesheetRoundingCommon


@tagged('post_install', '-at_install')
class TestRoundingValidation(TimesheetRoundingCommon):
    """The grid, as applied to entries created once the rule is in force."""

    # -- 15 minute step ------------------------------------------------

    def test_step_15_accepts_multiples(self):
        self._enable_rounding_for_new_entries('15')
        for hours in (0.25, 0.5, 0.75, 1.0, 1.25):
            entry = self._new_timesheet(hours)
            self.assertEqual(entry.unit_amount, hours)

    def test_step_15_rejects_20_minutes(self):
        self._enable_rounding_for_new_entries('15')
        with self.assertRaises(ValidationError):
            self._new_timesheet(1 / 3)

    def test_step_15_rejects_40_minutes(self):
        self._enable_rounding_for_new_entries('15')
        with self.assertRaises(ValidationError):
            self._new_timesheet(2 / 3)

    def test_step_15_rejects_70_minutes(self):
        self._enable_rounding_for_new_entries('15')
        with self.assertRaises(ValidationError):
            self._new_timesheet(7 / 6)

    # -- 30 minute step ------------------------------------------------

    def test_step_30_accepts_multiples(self):
        self._enable_rounding_for_new_entries('30')
        for hours in (0.5, 1.0, 1.5, 2.0):
            entry = self._new_timesheet(hours)
            self.assertEqual(entry.unit_amount, hours)

    def test_step_30_rejects_15_minutes(self):
        self._enable_rounding_for_new_entries('30')
        with self.assertRaises(ValidationError):
            self._new_timesheet(0.25)

    def test_step_30_rejects_45_minutes(self):
        self._enable_rounding_for_new_entries('30')
        with self.assertRaises(ValidationError):
            self._new_timesheet(0.75)

    # -- disabled ------------------------------------------------------

    def test_disabled_setting_allows_anything(self):
        self._disable_rounding()
        for hours in (1 / 3, 2 / 3, 7 / 6, 0.05):
            entry = self._new_timesheet(hours)
            self.assertAlmostEqual(entry.unit_amount, hours, places=10)

    # -- writes on covered entries -------------------------------------

    def test_write_to_invalid_value_is_rejected(self):
        self._enable_rounding_for_new_entries('15')
        entry = self._new_timesheet(0.5)
        with self.assertRaises(ValidationError):
            entry.unit_amount = 1 / 3

    def test_write_to_valid_value_passes(self):
        self._enable_rounding_for_new_entries('15')
        entry = self._new_timesheet(0.5)
        entry.unit_amount = 1.25
        self.assertEqual(entry.unit_amount, 1.25)

    def test_unrelated_write_does_not_validate(self):
        """The value comparison, not the boundary: an untouched duration is not rechecked."""
        self._enable_rounding_for_new_entries('15')
        entry = self._new_timesheet(0.5)
        entry.write({'name': 'renamed', 'unit_amount': 0.5})
        self.assertEqual(entry.name, 'renamed')

    # -- scope ---------------------------------------------------------

    def test_non_timesheet_analytic_line_is_not_checked(self):
        """Analytic lines without a project carry quantities, not durations."""
        self._enable_rounding_for_new_entries('15')
        line = self.env['account.analytic.line'].create({
            'name': 'plain analytic entry',
            'account_id': self.analytic_account.id,
            'unit_amount': 1 / 3,
        })
        self.assertAlmostEqual(line.unit_amount, 1 / 3, places=10)

    def test_skip_context_bypasses_the_check(self):
        """Escape hatch for automated flows that own the duration."""
        self._enable_rounding_for_new_entries('15')
        entry = self.env['account.analytic.line'] \
            .with_context(skip_timesheet_rounding_check=True) \
            .create({
                'name': 'imported entry',
                'project_id': self.project.id,
                'employee_id': self.employee.id,
                'unit_amount': 1 / 3,
            })
        self.assertAlmostEqual(entry.unit_amount, 1 / 3, places=10)


@tagged('post_install', '-at_install')
class TestExistingEntriesUntouched(TimesheetRoundingCommon):
    """The rule must not reach entries that predate it — in any way.

    This is the business requirement the module was reworked for: existing
    entries are neither validated, nor converted, nor frozen.
    """

    def test_enabling_setting_does_not_touch_existing_values(self):
        self._disable_rounding()
        values = (1 / 3, 2 / 3, 7 / 6)
        entries = [self._new_timesheet(hours) for hours in values]

        self._enable_rounding_after_existing_entries('15')

        for entry, expected in zip(entries, values):
            self.assertAlmostEqual(entry.unit_amount, expected, places=10)

    def test_existing_entry_stays_editable(self):
        entry = self._existing_timesheet(1 / 3)
        entry.name = 'edited description'
        self.assertEqual(entry.name, 'edited description')
        self.assertAlmostEqual(entry.unit_amount, 1 / 3, places=10)

    def test_existing_entry_duration_may_move_to_another_off_grid_value(self):
        """The point of the rework: a legacy entry accepts any duration.

        A PM correcting 20 min to 25 min on a historical entry must not be
        stopped by a rule that did not exist when the entry was logged.
        """
        entry = self._existing_timesheet(1 / 3)
        entry.unit_amount = 5 / 12  # 25 minutes, off the 15-minute grid
        self.assertAlmostEqual(entry.unit_amount, 5 / 12, places=10)

    def test_existing_entry_duration_may_move_to_an_on_grid_value(self):
        entry = self._existing_timesheet(1 / 3)
        entry.unit_amount = 0.5
        self.assertEqual(entry.unit_amount, 0.5)

    def test_existing_entry_is_not_converted_on_any_write(self):
        """No silent rounding anywhere: the stored value is what was written."""
        entry = self._existing_timesheet(7 / 6)
        entry.write({'name': 'touched'})
        self.assertAlmostEqual(entry.unit_amount, 7 / 6, places=10)

    def test_no_bulk_conversion_entry_point_remains(self):
        """The bulk wizard was removed with the requirement it served."""
        self.assertNotIn('timesheet.rounding.wizard', self.env)
        self.assertFalse(hasattr(
            self.env['account.analytic.line'],
            'action_open_timesheet_rounding_wizard',
        ))

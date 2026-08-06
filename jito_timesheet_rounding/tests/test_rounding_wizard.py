# -*- coding: utf-8 -*-

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import TimesheetRoundingCommon


@tagged('post_install', '-at_install')
class TestRoundingWizard(TimesheetRoundingCommon):
    """Requirement E: manual bulk conversion of hand-picked entries."""

    # ``_open_wizard`` and ``_make_off_grid`` live in TimesheetRoundingCommon.

    # -- how the wizard is built ---------------------------------------

    def test_action_creates_the_wizard_server_side(self):
        """The preview lines must exist in the database before the form loads.

        Regression guard. They used to be built as ``(0, 0, {...})`` commands in
        ``default_get``, and the web client dropped ``timesheet_id`` on the way
        back (it keeps only fields declared in the view), so confirming the
        wizard raised "a mandatory field is not set". Creating the record in the
        action removes the client round trip entirely.
        """
        timesheets = self._make_off_grid([1 / 3, 2 / 3])

        action = timesheets.action_open_timesheet_rounding_wizard()

        self.assertEqual(action['res_model'], 'timesheet.rounding.wizard')
        self.assertTrue(action.get('res_id'), "the wizard must be created, not left to default_get")

        wizard = self.env['timesheet.rounding.wizard'].browse(action['res_id'])
        self.assertEqual(len(wizard.line_ids), 2)
        self.assertEqual(wizard.line_ids.timesheet_id, timesheets)

    def test_preview_lines_are_persisted_before_apply(self):
        """Every line must carry its timesheet without any client interaction."""
        timesheets = self._make_off_grid([1 / 3])
        wizard = self._open_wizard(timesheets)

        wizard.line_ids.flush_recordset()
        self.assertTrue(all(wizard.line_ids.mapped('timesheet_id')))

    def test_context_path_still_builds_the_preview(self):
        """``default_get`` stays a working fallback for programmatic callers."""
        timesheets = self._make_off_grid([1 / 3])

        wizard = self.env['timesheet.rounding.wizard'].with_context(
            active_model='account.analytic.line',
            active_ids=timesheets.ids,
        ).create({})

        self.assertEqual(wizard.line_ids.timesheet_id, timesheets)

    def test_view_keeps_timesheet_id_savable(self):
        """Safety net for the client round trip, in case a caller skips the action.

        ``column_invisible`` puts the field in the client's activeFields (without
        it the value is dropped on parse) and ``force_save`` stops the readonly
        filter from stripping it on save. Both are required; neither is obvious
        from reading the view, hence this test.
        """
        arch = self.env.ref(
            'jito_timesheet_rounding.view_timesheet_rounding_wizard_form'
        ).arch

        self.assertIn('name="timesheet_id"', arch)
        node = arch.split('name="timesheet_id"')[1].split('/>')[0]
        self.assertIn('column_invisible', node)
        self.assertIn('force_save', node)

    # -- preview -------------------------------------------------------

    def test_preview_lists_every_selected_entry(self):
        timesheets = self._make_off_grid([1 / 3, 0.5, 2 / 3])
        wizard = self._open_wizard(timesheets)

        self.assertEqual(len(wizard.line_ids), 3)
        self.assertEqual(wizard.to_change_count, 2, "0:30 is already on the grid")
        self.assertEqual(wizard.unchanged_count, 1)

    def test_nothing_is_written_before_confirmation(self):
        timesheets = self._make_off_grid([1 / 3])
        self._open_wizard(timesheets)
        self.assertAlmostEqual(timesheets.unit_amount, 1 / 3, places=10)

    # -- methods -------------------------------------------------------

    def test_round_down(self):
        timesheets = self._make_off_grid([1 / 3])          # 00:20
        self._open_wizard(timesheets, 'down').action_apply()
        self.assertEqual(timesheets.unit_amount, 0.25)     # 00:15

    def test_round_up(self):
        timesheets = self._make_off_grid([1 / 3])          # 00:20
        self._open_wizard(timesheets, 'up').action_apply()
        self.assertEqual(timesheets.unit_amount, 0.5)      # 00:30

    def test_round_nearest(self):
        timesheets = self._make_off_grid([1 / 3, 2 / 3])   # 00:20 -> 00:15, 00:40 -> 00:45
        self._open_wizard(timesheets, 'nearest').action_apply()
        self.assertEqual(timesheets[0].unit_amount, 0.25)
        self.assertEqual(timesheets[1].unit_amount, 0.75)

    def test_nearest_on_step_30(self):
        self._disable_rounding()
        timesheet = self._new_timesheet(7 / 6)             # 01:10
        self._enable_rounding('30')
        self._open_wizard(timesheet, 'nearest').action_apply()
        self.assertEqual(timesheet.unit_amount, 1.0)       # 01:00

    # -- scope ---------------------------------------------------------

    def test_only_selected_entries_change(self):
        """Requirement E.2."""
        self._disable_rounding()
        selected = self._new_timesheet(1 / 3)
        untouched = self._new_timesheet(2 / 3)
        self._enable_rounding('15')

        self._open_wizard(selected, 'up').action_apply()

        self.assertEqual(selected.unit_amount, 0.5)
        self.assertAlmostEqual(untouched.unit_amount, 2 / 3, places=10)

    def test_already_on_grid_entries_are_not_rewritten(self):
        timesheets = self._make_off_grid([0.25, 0.5])
        with self.assertRaises(UserError):
            self._open_wizard(timesheets, 'nearest').action_apply()

    def test_wizard_requires_the_setting(self):
        self._disable_rounding()
        timesheet = self._new_timesheet(1 / 3)
        with self.assertRaises(UserError):
            timesheet.action_open_timesheet_rounding_wizard()

    def test_converted_value_passes_validation(self):
        """The conversion must produce a value the constraint accepts."""
        timesheets = self._make_off_grid([7 / 6])
        self._open_wizard(timesheets, 'nearest').action_apply()
        # writing it back unchanged must not raise
        timesheets.unit_amount = timesheets.unit_amount
        self.assertEqual(timesheets.unit_amount, 1.25)

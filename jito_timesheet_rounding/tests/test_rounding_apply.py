# -*- coding: utf-8 -*-

from odoo.tests import tagged

from ..models.rounding import round_to_grid
from .common import TimesheetRoundingCommon


@tagged('post_install', '-at_install')
class TestRoundToGrid(TimesheetRoundingCommon):
    """The pure helper, exercised where the interesting cases actually are."""

    def _assert_rounds(self, step, cases):
        for given, expected in cases:
            self.assertAlmostEqual(
                round_to_grid(self.hours(given), step) * 60.0, expected, places=6,
                msg="%s min on a %s min step should give %s min" % (given, step, expected),
            )

    def test_nearest_multiple_on_a_15_minute_step(self):
        self._assert_rounds(15, [
            (0, 0),
            (15, 15), (30, 30), (75, 75),     # already on the grid
            (20, 15), (40, 45), (70, 75),
            (67, 60), (68, 75),
            (80, 75), (83, 90),
        ])

    def test_ties_go_up_not_to_even(self):
        """``round()`` is banker's rounding and would send 67.5 down but 97.5 up."""
        self._assert_rounds(15, [(7.5, 15), (22.5, 30), (67.5, 75), (97.5, 105)])

    def test_nearest_multiple_on_a_30_minute_step(self):
        self._assert_rounds(30, [
            (30, 30), (60, 60),
            (14, 30), (16, 30), (44, 30), (46, 60), (45, 60),
        ])

    def test_non_zero_never_collapses_to_zero(self):
        """A logged minute is work; rounding it away leaves a 0:00 row that reads as a bug."""
        self._assert_rounds(15, [(1, 15), (5, 15), (7, 15), (7.4, 15)])
        self._assert_rounds(30, [(1, 30), (14, 30)])

    def test_exact_zero_stays_zero(self):
        self._assert_rounds(15, [(0, 0)])
        self.assertEqual(round_to_grid(0.0, 15), 0.0)

    def test_no_step_leaves_the_value_alone(self):
        self.assertEqual(round_to_grid(1 / 3, 0), 1 / 3)

    def test_on_grid_values_are_returned_identical(self):
        """Not merely equal: rebuilding them would issue pointless UPDATEs."""
        for hours in (0.25, 0.5, 1.25, 7.75):
            self.assertIs(round_to_grid(hours, 15), hours)

    def test_negative_durations_keep_their_sign(self):
        self._assert_rounds(15, [(-20, -15), (-40, -45), (-1, -15)])


@tagged('post_install', '-at_install')
class TestRoundingOnCreate(TimesheetRoundingCommon):

    def test_off_grid_entry_is_rounded_on_creation(self):
        self._enable_rounding('15')
        self.assertMinutes(self._new_timesheet(20), 15)
        self.assertMinutes(self._new_timesheet(40), 45)
        self.assertMinutes(self._new_timesheet(70), 75)

    def test_on_grid_entry_is_stored_untouched(self):
        self._enable_rounding('15')
        for minutes in (15, 30, 45, 60, 75):
            self.assertMinutes(self._new_timesheet(minutes), minutes)

    def test_small_entry_is_raised_to_one_step(self):
        self._enable_rounding('15')
        self.assertMinutes(self._new_timesheet(5), 15)

    def test_empty_entry_stays_empty(self):
        self._enable_rounding('15')
        self.assertMinutes(self._new_timesheet(0), 0)

    def test_30_minute_step(self):
        self._enable_rounding('30')
        self.assertMinutes(self._new_timesheet(15), 30)
        self.assertMinutes(self._new_timesheet(40), 30)
        self.assertMinutes(self._new_timesheet(50), 60)

    def test_disabled_setting_stores_the_value_as_entered(self):
        self._disable_rounding()
        for minutes in (20, 40, 70, 3):
            self.assertMinutes(self._new_timesheet(minutes), minutes)

    def test_a_batch_create_rounds_every_line(self):
        """``create()`` is ``model_create_multi``; the grid must not stop at the first line."""
        self._enable_rounding('15')
        lines = self.env['account.analytic.line'].create([{
            'name': 'batch %s' % minutes,
            'project_id': self.project.id,
            'employee_id': self.employee.id,
            'unit_amount': self.hours(minutes),
        } for minutes in (20, 40, 70)])
        self.assertEqual(
            [round(line.unit_amount * 60.0) for line in lines], [15, 45, 75],
        )


@tagged('post_install', '-at_install')
class TestRoundingOnWrite(TimesheetRoundingCommon):

    def test_edited_duration_is_rounded(self):
        self._enable_rounding('15')
        entry = self._new_timesheet(30)
        entry.unit_amount = self.hours(82)
        self.assertMinutes(entry, 75)

    def test_editing_a_legacy_entry_duration_rounds_it(self):
        """Confirmed requirement: whatever a user types now lands on the grid."""
        entry = self._existing_timesheet(70)
        entry.unit_amount = self.hours(82)
        self.assertMinutes(entry, 75)

    def test_a_legacy_entry_keeps_its_value_until_its_duration_is_edited(self):
        """Stored history is never rewritten in place — only what is re-entered."""
        entry = self._existing_timesheet(70)
        entry.write({'name': 'renamed'})
        self.assertMinutes(entry, 70)
        self.assertEqual(entry.name, 'renamed')

    def test_writing_the_same_off_grid_value_does_not_round_it(self):
        """Some flows resend every field. Only a duration that moves is snapped."""
        entry = self._existing_timesheet(70)
        entry.write({'name': 'renamed', 'unit_amount': entry.unit_amount})
        self.assertMinutes(entry, 70)

    def test_enabling_the_setting_changes_no_stored_value(self):
        self._disable_rounding()
        entries = [self._new_timesheet(minutes) for minutes in (20, 40, 70)]
        self._enable_rounding('15')
        for entry, minutes in zip(entries, (20, 40, 70)):
            self.assertMinutes(entry, minutes)

    def test_a_multi_record_write_rounds_each_line_by_its_own_scope(self):
        """One ``vals``, several scopes: the in-scope line is snapped, the others are not."""
        self._enable_rounding('15')
        timesheet = self._new_timesheet(30)
        plain = self.env['account.analytic.line'].create({
            'name': 'plain analytic entry',
            'account_id': self.analytic_account.id,
            'unit_amount': 1.0,
        })

        (timesheet | plain).write({'unit_amount': self.hours(82)})

        self.assertMinutes(timesheet, 75)
        self.assertMinutes(plain, 82, "A quantity is not a duration and must not be rounded.")

    def test_no_bulk_conversion_entry_point_exists(self):
        """Rounding happens on save, never as a sweep over stored rows."""
        self.assertNotIn('timesheet.rounding.wizard', self.env)
        self.assertFalse(hasattr(
            self.env['account.analytic.line'],
            'action_open_timesheet_rounding_wizard',
        ))


@tagged('post_install', '-at_install')
class TestRoundingOnChange(TimesheetRoundingCommon):
    """The correction the user sees happen, before anything is saved."""

    def _edit(self, minutes):
        """A record as the form has it: in memory, not yet written."""
        line = self.env['account.analytic.line'].new({
            'name': 'onchange entry',
            'project_id': self.project.id,
            'employee_id': self.employee.id,
            'unit_amount': self.hours(minutes),
        })
        return line, line._onchange_unit_amount_round_to_step()

    def test_off_grid_value_is_corrected_in_place(self):
        self._enable_rounding('15')
        line, _warning = self._edit(82)
        self.assertMinutes(line, 75)

    def test_the_message_is_a_notification_not_a_dialog(self):
        """A modal would be the wrong weight: nothing went wrong here."""
        self._enable_rounding('15')
        _line, result = self._edit(82)
        self.assertEqual(result['warning']['type'], 'notification')

    def test_the_message_speaks_in_hours_and_minutes(self):
        """1.37 -> 1.25 would be meaningless to whoever typed 1:22."""
        self._enable_rounding('15')
        _line, result = self._edit(82)
        message = result['warning']['message']
        self.assertIn('1:22', message)
        self.assertIn('1:15', message)
        self.assertNotIn('1.3', message)

    def test_the_step_is_named_in_the_message(self):
        self._enable_rounding('30')
        line, result = self._edit(82)
        self.assertMinutes(line, 90)
        self.assertIn('30', result['warning']['title'])

    def test_an_on_grid_value_says_nothing(self):
        self._enable_rounding('15')
        line, result = self._edit(75)
        self.assertIsNone(result)
        self.assertMinutes(line, 75)

    def test_small_value_is_raised_and_explained(self):
        self._enable_rounding('15')
        line, result = self._edit(5)
        self.assertMinutes(line, 15)
        self.assertIn('0:15', result['warning']['message'])

    def test_nothing_happens_when_rounding_is_disabled(self):
        self._disable_rounding()
        line, result = self._edit(82)
        self.assertIsNone(result)
        self.assertMinutes(line, 82)

    def test_nothing_happens_on_a_non_timesheet_line(self):
        """Quantities are not durations; the form must not touch them."""
        self._enable_rounding('15')
        line = self.env['account.analytic.line'].new({
            'name': 'plain analytic entry',
            'account_id': self.analytic_account.id,
            'unit_amount': 1 / 3,
        })
        self.assertIsNone(line._onchange_unit_amount_round_to_step())
        self.assertAlmostEqual(line.unit_amount, 1 / 3, places=10)

    def test_it_agrees_with_what_would_have_been_stored(self):
        """The whole point: the preview must not differ from the saved value."""
        self._enable_rounding('15')
        for minutes in (5, 20, 40, 68, 82, 0, 45):
            line, _warning = self._edit(minutes)
            previewed = line.unit_amount
            self.assertAlmostEqual(
                previewed, self._new_timesheet(minutes).unit_amount, places=10,
                msg="onchange and create disagree on %s minutes" % minutes,
            )


@tagged('post_install', '-at_install')
class TestGridCellRounding(TimesheetRoundingCommon):
    """What the grid view needs from the server to correct a cell in place."""

    def test_a_grid_cell_edit_stores_a_rounded_value(self):
        """``grid_update_cell`` writes through this model like anything else."""
        self._enable_rounding('15')
        entry = self._new_timesheet(30)
        self.env['account.analytic.line'].with_context(
            default_project_id=self.project.id,
        ).grid_update_cell(
            [('id', '=', entry.id)], 'unit_amount', self.hours(22),
        )
        self.assertMinutes(entry, 45, "0:30 + 0:22 = 0:52, which rounds to 0:45")

    def test_the_cell_total_the_grid_re_reads_matches_what_was_stored(self):
        """The patch re-reads with read_group; it must see the rounded figure."""
        self._enable_rounding('15')
        entry = self._new_timesheet(30)
        self.env['account.analytic.line'].with_context(
            default_project_id=self.project.id,
        ).grid_update_cell(
            [('id', '=', entry.id)], 'unit_amount', self.hours(22),
        )
        [group] = self.env['account.analytic.line'].read_group(
            [('id', '=', entry.id)], ['unit_amount'], [], lazy=False,
        )
        self.assertAlmostEqual(group['unit_amount'] * 60.0, 45, places=6)


@tagged('post_install', '-at_install')
class TestRoundingScope(TimesheetRoundingCommon):

    def test_non_timesheet_analytic_line_is_not_rounded(self):
        """Lines without a project carry quantities, not durations."""
        self._enable_rounding('15')
        line = self.env['account.analytic.line'].create({
            'name': 'plain analytic entry',
            'account_id': self.analytic_account.id,
            'unit_amount': 1 / 3,
        })
        self.assertAlmostEqual(line.unit_amount, 1 / 3, places=10)

    def test_leave_timesheets_keep_the_exact_leave_duration(self):
        """``project_timesheet_holidays`` writes the schedule's hours; the leave owns them.

        Skipped when that module is not installed — it is not a dependency here.
        """
        line_fields = self.env['account.analytic.line']._fields
        if 'global_leave_id' not in line_fields:
            self.skipTest("project_timesheet_holidays is not installed")

        self._enable_rounding('15')
        calendar_leave = self.env['resource.calendar.leaves'].create({
            'name': 'Rounding Test Global Leave',
            'date_from': '2026-01-05 08:00:00',
            'date_to': '2026-01-05 17:00:00',
            'company_id': self.company.id,
        })
        entry = self.env['account.analytic.line'].create({
            'name': 'leave entry',
            'project_id': self.project.id,
            'employee_id': self.employee.id,
            'unit_amount': self.hours(456),  # 7.6 h, a real working-schedule day
            'global_leave_id': calendar_leave.id,
        })
        self.assertMinutes(entry, 456)

        entry.unit_amount = self.hours(457)
        self.assertMinutes(entry, 457)

    def test_skip_context_bypasses_rounding(self):
        """Escape hatch for imports and data fixes that own the duration."""
        self._enable_rounding('15')
        entry = self.env['account.analytic.line'] \
            .with_context(skip_timesheet_rounding_check=True) \
            .create({
                'name': 'imported entry',
                'project_id': self.project.id,
                'employee_id': self.employee.id,
                'unit_amount': 1 / 3,
            })
        self.assertAlmostEqual(entry.unit_amount, 1 / 3, places=10)

        entry.with_context(skip_timesheet_rounding_check=True).unit_amount = 2 / 3
        self.assertAlmostEqual(entry.unit_amount, 2 / 3, places=10)

    def test_the_rule_is_per_company(self):
        self._disable_rounding()
        other = self.env['res.company'].create({
            'name': 'Rounding Test Co',
            'timesheet_rounding_enabled': True,
            'timesheet_rounding_step': '15',
        })
        project = self.env['project.project'].create({
            'name': 'Other Co Project',
            'allow_timesheets': True,
            'company_id': other.id,
        })
        employee = self.env['hr.employee'].create({
            'name': 'Other Co Employee',
            'company_id': other.id,
        })

        self.assertMinutes(
            self._new_timesheet(20), 20,
            "Rounding is off on this company and must stay off.",
        )

        entry = self.env['account.analytic.line'].with_company(other).create({
            'name': 'other co entry',
            'project_id': project.id,
            'employee_id': employee.id,
            'unit_amount': self.hours(20),
        })
        self.assertMinutes(entry, 15)

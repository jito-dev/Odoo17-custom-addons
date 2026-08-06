# -*- coding: utf-8 -*-

from datetime import timedelta

from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import TimesheetRoundingCommon


@tagged('post_install', '-at_install')
class TestRoundingBoundary(TimesheetRoundingCommon):
    """How the "existing vs new" boundary is stamped and honoured."""

    # -- stamping ------------------------------------------------------

    def test_enabling_stamps_the_boundary(self):
        self.company.timesheet_rounding_start_date = False
        self._enable_rounding('15')
        self.assertEqual(
            self.company.timesheet_rounding_start_date, self.env.cr.now(),
            "The boundary must come from the transaction clock, the same source "
            "create_date is filled from.",
        )

    def test_disabling_and_re_enabling_keeps_the_original_boundary(self):
        """Otherwise entries logged in between would retroactively become new."""
        original = self.env.cr.now() - timedelta(days=30)
        self._enable_rounding('15', start_date=original)

        self._disable_rounding()
        self._enable_rounding('15')

        self.assertEqual(self.company.timesheet_rounding_start_date, original)

    def test_explicit_boundary_is_not_overwritten(self):
        chosen = self.env.cr.now() - timedelta(days=7)
        self.company.timesheet_rounding_start_date = False
        self._enable_rounding('15', start_date=chosen)
        self.assertEqual(self.company.timesheet_rounding_start_date, chosen)

    def test_enabling_on_create_stamps_the_boundary(self):
        company = self.env['res.company'].create({
            'name': 'Rounding Test Co',
            'timesheet_rounding_enabled': True,
            'timesheet_rounding_step': '15',
        })
        self.assertEqual(company.timesheet_rounding_start_date, self.env.cr.now())

    def test_stamping_only_touches_companies_without_a_boundary(self):
        """A multi-company write must not reset a boundary that already exists."""
        original = self.env.cr.now() - timedelta(days=30)
        self.company.write({
            'timesheet_rounding_enabled': False,
            'timesheet_rounding_start_date': original,
        })
        other = self.env['res.company'].create({'name': 'Rounding Test Co 2'})

        (self.company | other).write({
            'timesheet_rounding_enabled': True,
            'timesheet_rounding_step': '30',
        })

        self.assertEqual(self.company.timesheet_rounding_start_date, original)
        self.assertEqual(other.timesheet_rounding_start_date, self.env.cr.now())
        self.assertEqual(self.company.timesheet_rounding_step, '30')
        self.assertEqual(other.timesheet_rounding_step, '30')

    # -- honouring the boundary ----------------------------------------

    def test_entry_created_exactly_at_the_boundary_is_new(self):
        """``>=``: the transaction that enables the rule is already covered."""
        self._enable_rounding('15', start_date=self.env.cr.now())
        with self.assertRaises(ValidationError):
            self._new_timesheet(1 / 3)

    def test_entry_created_before_the_boundary_is_not_checked(self):
        self._enable_rounding('15', start_date=self.env.cr.now() + timedelta(seconds=1))
        entry = self._new_timesheet(1 / 3)
        self.assertAlmostEqual(entry.unit_amount, 1 / 3, places=10)

    def test_enabled_without_a_boundary_validates_nothing(self):
        """Fail-safe direction.

        ``res.company.write()`` makes this unreachable through normal use. If a
        data fix ever clears the date, the module must fall back to leaving every
        entry alone rather than suddenly enforcing the grid on all history.
        """
        self._enable_rounding('15')
        self.company.timesheet_rounding_start_date = False

        entry = self._new_timesheet(1 / 3)
        self.assertAlmostEqual(entry.unit_amount, 1 / 3, places=10)

        entry.unit_amount = 2 / 3
        self.assertAlmostEqual(entry.unit_amount, 2 / 3, places=10)

    def test_boundary_is_per_company(self):
        """The step is per company, and so is the boundary that goes with it."""
        other = self.env['res.company'].create({
            'name': 'Rounding Test Co 3',
            'timesheet_rounding_enabled': True,
            'timesheet_rounding_step': '15',
            'timesheet_rounding_start_date': self.env.cr.now() + timedelta(seconds=1),
        })
        self._enable_rounding('15', start_date=self.env.cr.now() - timedelta(seconds=1))

        project = self.env['project.project'].create({
            'name': 'Other Co Project',
            'allow_timesheets': True,
            'company_id': other.id,
        })
        employee = self.env['hr.employee'].create({
            'name': 'Other Co Employee',
            'company_id': other.id,
        })

        # Covered company rejects...
        with self.assertRaises(ValidationError):
            self._new_timesheet(1 / 3)

        # ...while the company whose boundary is still ahead does not.
        entry = self.env['account.analytic.line'].with_company(other).create({
            'name': 'other co entry',
            'project_id': project.id,
            'employee_id': employee.id,
            'unit_amount': 1 / 3,
        })
        self.assertAlmostEqual(entry.unit_amount, 1 / 3, places=10)

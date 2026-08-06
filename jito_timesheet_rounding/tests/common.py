# -*- coding: utf-8 -*-

from odoo.tests import TransactionCase


class TimesheetRoundingCommon(TransactionCase):
    """Fixtures shared by the rounding tests.

    Durations are written in minutes and converted here, so the expectations in
    the tests read the way the rule is stated ("68 minutes becomes 75") instead
    of as decimal hours nobody can check at a glance.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.company = cls.env.company

        cls.analytic_plan = cls.env['account.analytic.plan'].create({
            'name': 'Rounding Test Plan',
        })
        cls.analytic_account = cls.env['account.analytic.account'].create({
            'name': 'Rounding Test Analytic',
            'plan_id': cls.analytic_plan.id,
            'company_id': cls.company.id,
        })
        cls.project = cls.env['project.project'].create({
            'name': 'Rounding Test Project',
            'allow_timesheets': True,
            'company_id': cls.company.id,
        })
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Rounding Test Employee',
            'company_id': cls.company.id,
        })

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def hours(minutes):
        """Minutes as the decimal hours ``unit_amount`` stores."""
        return minutes / 60.0

    def assertMinutes(self, entry, expected_minutes, msg=None):
        self.assertAlmostEqual(
            entry.unit_amount * 60.0, expected_minutes, places=6, msg=msg,
        )

    # ------------------------------------------------------------------
    # configuration
    # ------------------------------------------------------------------

    def _enable_rounding(self, step='15'):
        self.company.write({
            'timesheet_rounding_enabled': True,
            'timesheet_rounding_step': step,
        })

    def _disable_rounding(self):
        self.company.write({'timesheet_rounding_enabled': False})

    # ------------------------------------------------------------------
    # records
    # ------------------------------------------------------------------

    def _new_timesheet(self, minutes, name='test entry'):
        return self.env['account.analytic.line'].create({
            'name': name,
            'project_id': self.project.id,
            'employee_id': self.employee.id,
            'unit_amount': self.hours(minutes),
        })

    def _existing_timesheet(self, minutes, name='legacy entry'):
        """An off-grid entry logged before the rule was switched on."""
        self._disable_rounding()
        entry = self._new_timesheet(minutes, name=name)
        self._enable_rounding()
        return entry

# -*- coding: utf-8 -*-

from datetime import timedelta

from odoo.tests import TransactionCase


class TimesheetRoundingCommon(TransactionCase):
    """Base fixtures plus the two ways of placing entries around the boundary.

    ``create_date`` is filled from ``cr.now()``, the transaction clock, so every
    record a test creates carries the *same* timestamp. Tests therefore never try
    to age a record — they move the company boundary instead:

    - boundary one second in the past  -> every entry in the test is "new"
    - boundary one second in the future -> every entry in the test is "existing"
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
    # configuration
    # ------------------------------------------------------------------

    def _enable_rounding(self, step, start_date=None):
        """Enable the rule. Without ``start_date``, the company stamps its own."""
        values = {
            'timesheet_rounding_enabled': True,
            'timesheet_rounding_step': step,
        }
        if start_date is not None:
            values['timesheet_rounding_start_date'] = start_date
        self.company.write(values)

    def _enable_rounding_for_new_entries(self, step='15'):
        """Boundary in the past: entries this test creates are covered by the rule."""
        self._enable_rounding(step, start_date=self.env.cr.now() - timedelta(seconds=1))

    def _enable_rounding_after_existing_entries(self, step='15'):
        """Boundary in the future: entries this test creates predate the rule."""
        self._enable_rounding(step, start_date=self.env.cr.now() + timedelta(seconds=1))

    def _disable_rounding(self):
        self.company.write({'timesheet_rounding_enabled': False})

    # ------------------------------------------------------------------
    # records
    # ------------------------------------------------------------------

    def _new_timesheet(self, hours, name='test entry'):
        return self.env['account.analytic.line'].create({
            'name': name,
            'project_id': self.project.id,
            'employee_id': self.employee.id,
            'unit_amount': hours,
        })

    def _existing_timesheet(self, hours, name='legacy entry'):
        """An off-grid entry that predates the rule, built the way history did.

        Created while the rule is off, then the rule is switched on with its
        boundary after the entry — exactly the production situation.
        """
        self._disable_rounding()
        entry = self._new_timesheet(hours, name=name)
        self._enable_rounding_after_existing_entries()
        return entry

# -*- coding: utf-8 -*-

from odoo.tests import TransactionCase


class TimesheetRoundingCommon(TransactionCase):

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

    def _enable_rounding(self, step):
        self.company.write({
            'timesheet_rounding_enabled': True,
            'timesheet_rounding_step': step,
        })

    def _disable_rounding(self):
        self.company.write({'timesheet_rounding_enabled': False})

    def _new_timesheet(self, hours, name='test entry'):
        return self.env['account.analytic.line'].create({
            'name': name,
            'project_id': self.project.id,
            'employee_id': self.employee.id,
            'unit_amount': hours,
        })

    def _open_wizard(self, timesheets, method='nearest'):
        """Open the wizard exactly the way the UI does.

        Going through the action (rather than ``create({})`` with ``active_ids``)
        is deliberate: the preview lines are built server-side there, and that is
        the path the list header button takes. Building the wizard directly in a
        test would skip it and hide regressions in it.
        """
        action = timesheets.action_open_timesheet_rounding_wizard()
        wizard = self.env['timesheet.rounding.wizard'].browse(action['res_id'])
        wizard.rounding_method = method
        return wizard

    def _make_off_grid(self, values):
        """Create timesheets that the grid would reject, then enable the grid."""
        self._disable_rounding()
        timesheets = self.env['account.analytic.line']
        for value in values:
            timesheets |= self._new_timesheet(value)
        self._enable_rounding('15')
        return timesheets

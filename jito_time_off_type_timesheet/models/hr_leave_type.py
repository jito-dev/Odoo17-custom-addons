# -*- coding: utf-8 -*-
from odoo import api, models


class HolidaysType(models.Model):
    _inherit = "hr.leave.type"

    @api.depends('timesheet_task_id', 'company_id')
    def _compute_timesheet_generate(self):
        """Override to remove timesheet_project_id from depends.

        The Enterprise implementation depends on both timesheet_task_id AND
        timesheet_project_id. Because _compute_timesheet_project_id fires
        whenever company_id changes (including when the user sets a project
        manually), this creates a circular trigger:

            user checks timesheet_generate
            → onchange sets timesheet_project_id
            → _compute_timesheet_project_id re-runs (project resets)
            → _compute_timesheet_generate re-runs
            → finds no task yet → sets timesheet_generate = False

        By depending only on timesheet_task_id (and company_id for the global
        leave type shortcut), the checkbox stays stable after the user checks
        it and before they select a task.

        Semantics are preserved:
          - Global leave types (no company_id): always True
          - Company-scoped types: True iff a task is set
        The _check_timesheet_generate constraint still enforces both project
        and task on save.
        """
        for leave_type in self:
            leave_type.timesheet_generate = (
                not leave_type.company_id
                or bool(leave_type.timesheet_task_id)
            )

    @api.onchange('timesheet_generate')
    def _onchange_timesheet_generate(self):
        """Drive project/task fields when the checkbox is toggled.

        - Checking the box: silently pre-fill the Internal project so the
          task domain is immediately scoped and quick-create works.
        - Unchecking the box: clear both project and task.

        Global leave types (no company_id) are unaffected because the
        checkbox is always True for them and they don't reach this onchange
        in a meaningful way.
        """
        if self.timesheet_generate and self.company_id:
            if not self.timesheet_project_id:
                self.timesheet_project_id = self.company_id.internal_project_id
        elif not self.timesheet_generate:
            self.timesheet_project_id = False
            self.timesheet_task_id = False

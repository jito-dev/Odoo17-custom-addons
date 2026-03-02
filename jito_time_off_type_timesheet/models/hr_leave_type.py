# -*- coding: utf-8 -*-
from odoo import api, fields, models


class HolidaysType(models.Model):
    _inherit = "hr.leave.type"

    # -------------------------------------------------------------------------
    # Helper field — non-stored, computed fresh on every read.
    #
    # The Enterprise _compute_timesheet_project_id sets timesheet_project_id to
    # company.internal_project_id for company-scoped types, but leaves it as
    # False for global types (company_id = False).
    #
    # For global types timesheet_generate is always True (computed), but the
    # task field is invisible when timesheet_project_id is False — so users
    # can never configure the task on global leave types through the normal UI.
    #
    # This field resolves that by returning timesheet_project_id when set, or
    # falling back to env.company.internal_project_id for global types.
    # The view uses this field exclusively for task domain, context, and
    # visibility — the actual stored timesheet_project_id is never changed.
    # -------------------------------------------------------------------------
    timesheet_project_for_task = fields.Many2one(
        'project.project',
        compute='_compute_timesheet_project_for_task',
        string='Effective Timesheet Project',
    )

    @api.depends('timesheet_project_id', 'company_id')
    def _compute_timesheet_project_for_task(self):
        """Return timesheet_project_id when set, else env.company.internal_project_id.

        This allows global leave types (no company_id, timesheet_project_id=False)
        to expose the task configuration UI using the current user's company
        Internal project as the target for task creation.
        """
        fallback = self.env.company.internal_project_id
        for leave in self:
            leave.timesheet_project_for_task = leave.timesheet_project_id or fallback

    # -------------------------------------------------------------------------
    # Override _compute_timesheet_generate
    # -------------------------------------------------------------------------

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

    # -------------------------------------------------------------------------
    # Onchange
    # -------------------------------------------------------------------------

    @api.onchange('timesheet_generate')
    def _onchange_timesheet_generate(self):
        """Drive project/task fields when the checkbox is toggled.

        - Checking the box: silently pre-fill the Internal project so the
          task domain is immediately scoped and quick-create works.
          For company-scoped types uses company_id.internal_project_id.
          For global types (no company_id) uses env.company.internal_project_id
          so that the task field becomes usable even on global leave types.
        - Unchecking the box: clear both project and task.
        """
        if self.timesheet_generate:
            company = self.company_id or self.env.company
            if not self.timesheet_project_id:
                self.timesheet_project_id = company.internal_project_id
        elif not self.timesheet_generate:
            self.timesheet_project_id = False
            self.timesheet_task_id = False

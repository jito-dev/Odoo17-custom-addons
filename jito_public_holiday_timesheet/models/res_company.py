# -*- coding: utf-8 -*-
from odoo import fields, models, _


class Company(models.Model):
    _inherit = 'res.company'

    public_holiday_timesheet_task_id = fields.Many2one(
        'project.task',
        string="Public Holidays Task",
        domain="[('project_id', '=', internal_project_id)]",
        help="Task used when generating timesheets for public holidays. "
             "If not set, falls back to the standard 'Time Off' task.",
    )

    def _create_internal_project_task(self):
        """Extend to also create a 'Public Holidays' task alongside the
        standard 'Time Off' task whenever a new internal project is created.
        """
        projects = super()._create_internal_project_task()
        for project in projects:
            company = project.company_id
            company = company.with_company(company)
            if not company.public_holiday_timesheet_task_id:
                task = company.env['project.task'].sudo().create({
                    'name': _('Public Holidays'),
                    'project_id': company.internal_project_id.id,
                    'active': True,
                    'company_id': company.id,
                })
                company.write({'public_holiday_timesheet_task_id': task.id})
        return projects

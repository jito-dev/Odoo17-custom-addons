# -*- coding: utf-8 -*-
from . import models
from odoo import _


def post_init(env):
    """Create 'Public Holidays' task for existing companies that already have
    an internal project set up (i.e. project_timesheet_holidays was already
    installed before this module).
    """
    companies = env['res.company'].search([
        ('internal_project_id', '!=', False),
        ('public_holiday_timesheet_task_id', '=', False),
    ])
    for company in companies:
        company = company.with_company(company)
        task = company.env['project.task'].sudo().create({
            'name': _('Public Holidays'),
            'project_id': company.internal_project_id.id,
            'active': True,
            'company_id': company.id,
        })
        company.write({'public_holiday_timesheet_task_id': task.id})

# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    public_holiday_timesheet_task_id = fields.Many2one(
        related='company_id.public_holiday_timesheet_task_id',
        string="Public Holidays Task",
        readonly=False,
        domain="[('company_id', '=', company_id), ('project_id', '=?', internal_project_id)]",
        help="Task used when generating timesheets for public holidays. "
             "If not set, falls back to the standard 'Time Off' task.",
    )

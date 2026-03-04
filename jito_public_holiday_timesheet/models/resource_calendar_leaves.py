# -*- coding: utf-8 -*-
from odoo import models, _


class ResourceCalendarLeaves(models.Model):
    _inherit = "resource.calendar.leaves"

    def _timesheet_prepare_line_values(self, index, employee_id, work_hours_data, day_date, work_hours_count):
        """Override to use the dedicated 'Public Holidays' task and to include
        the actual holiday name in the timesheet description.

        Behaviour:
        - If ``public_holiday_timesheet_task_id`` is configured on the company,
          the generated timesheet line will use that task and a description of
          the form "<Holiday name> (x/y)" (e.g. "Christmas Day (1/1)").
        - If the field is not set the method falls back to the standard Odoo
          behaviour (task = leave_timesheet_task_id, name = "Time Off (x/y)").
        """
        values = super()._timesheet_prepare_line_values(
            index, employee_id, work_hours_data, day_date, work_hours_count
        )
        public_holiday_task = employee_id.company_id.public_holiday_timesheet_task_id
        if public_holiday_task:
            holiday_name = self.name or _("Public Holiday")
            values['task_id'] = public_holiday_task.id
            values['name'] = _("%s (%s/%s)", holiday_name, index + 1, len(work_hours_data))
        return values

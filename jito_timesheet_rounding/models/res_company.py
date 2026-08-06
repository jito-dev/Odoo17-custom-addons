# -*- coding: utf-8 -*-

from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    timesheet_rounding_enabled = fields.Boolean(
        string='Enable Company Hours Tracking Rounding',
        default=False,
        help="Require tracked time (Hours Spent) to be a multiple of the tracking step. "
             "Entries are never rounded automatically: a non-conforming duration is "
             "rejected so the user can adjust it.",
    )

    timesheet_rounding_step = fields.Selection(
        selection=[('15', '15 minutes'), ('30', '30 minutes')],
        string='Tracking Step',
        default='15',
        help="Granularity tracked time must follow when rounding is enabled.",
    )

    def _timesheet_rounding_minutes(self):
        """Tracking step in minutes, or 0 when rounding is off for this company."""
        self.ensure_one()
        if not self.timesheet_rounding_enabled:
            return 0
        return int(self.timesheet_rounding_step or 0)

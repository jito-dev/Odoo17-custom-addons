# -*- coding: utf-8 -*-

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    timesheet_rounding_enabled = fields.Boolean(
        related='company_id.timesheet_rounding_enabled',
        readonly=False,
    )
    timesheet_rounding_step = fields.Selection(
        related='company_id.timesheet_rounding_step',
        readonly=False,
    )

    def set_values(self):
        """Keep the timer on the same grid as the tracking step.

        ``timesheet_grid`` rounds every timer stop up to
        ``timesheet_grid.timesheet_rounding`` minutes and enforces
        ``timesheet_min_duration`` as a floor. Both are global system parameters,
        not per-company ones. If they stayed at their own value the timer would
        happily produce, say, 15-minute entries while the company step is 30, and
        the user would get a validation error on Stop with no way to fix it.

        So when rounding is enabled we align both parameters with the step. The
        timer keeps the visible round-up behaviour Odoo has always had, only on
        the right grid. When rounding is disabled the parameters are left alone.

        Known limitation: these parameters are global, so with several companies
        using different steps the last saved one wins for the timer.
        """
        res = super().set_values()
        for settings in self:
            step = settings.company_id._timesheet_rounding_minutes()
            if not step:
                continue
            params = self.env['ir.config_parameter'].sudo()
            params.set_param('timesheet_grid.timesheet_min_duration', step)
            params.set_param('timesheet_grid.timesheet_rounding', step)
        return res

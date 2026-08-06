# -*- coding: utf-8 -*-

from odoo import api, fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    timesheet_rounding_enabled = fields.Boolean(
        string='Enable Company Hours Tracking Rounding',
        default=False,
        help="Require tracked time (Hours Spent) to be a multiple of the tracking step. "
             "Entries are never rounded automatically: a non-conforming duration is "
             "rejected so the user can adjust it. Only entries created after the rule "
             "was switched on are concerned.",
    )

    timesheet_rounding_step = fields.Selection(
        selection=[('15', '15 minutes'), ('30', '30 minutes')],
        string='Tracking Step',
        default='15',
        help="Granularity tracked time must follow when rounding is enabled.",
    )

    timesheet_rounding_start_date = fields.Datetime(
        string='Rounding Applies From',
        help="Entries created from this moment on must follow the tracking step. "
             "Everything created before it keeps its value and stays editable. "
             "Stamped automatically the first time rounding is enabled and kept "
             "afterwards, so switching the setting off and on again does not move "
             "the boundary.",
    )

    def _timesheet_rounding_minutes(self):
        """Tracking step in minutes, or 0 when rounding is off for this company."""
        self.ensure_one()
        if not self.timesheet_rounding_enabled:
            return 0
        return int(self.timesheet_rounding_step or 0)

    def _timesheet_rounding_start(self):
        """Moment from which the grid applies, or ``False`` when it never does.

        ``False`` means "no entry is concerned". That is the safe direction: the
        business rule is that pre-existing entries must never be blocked, so an
        unstamped company validates nothing rather than validating everything.
        In practice ``write()`` below guarantees the stamp exists whenever the
        setting is on.
        """
        self.ensure_one()
        if not self._timesheet_rounding_minutes():
            return False
        return self.timesheet_rounding_start_date

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('timesheet_rounding_enabled') and not vals.get('timesheet_rounding_start_date'):
                vals['timesheet_rounding_start_date'] = self.env.cr.now()
        return super().create(vals_list)

    def write(self, vals):
        """Stamp the boundary the first time rounding is switched on.

        Done here rather than in ``res.config.settings.set_values()`` so that
        every path is covered — the settings screen, a direct write on the
        company, a data file, a test. A company with the setting on but no date
        would silently validate nothing.

        ``cr.now()`` is used, not ``fields.Datetime.now()``: it is the same clock
        ``create_date`` is filled from (``_prepare_create_values``), so the
        comparison in ``account.analytic.line`` is exact rather than off by up to
        a second. Entries created in the very transaction that enables the rule
        share that timestamp and count as new.
        """
        if vals.get('timesheet_rounding_enabled') and 'timesheet_rounding_start_date' not in vals:
            unstamped = self.filtered(lambda c: not c.timesheet_rounding_start_date)
            if unstamped:
                now = self.env.cr.now()
                # Written separately: the stamp is per company, and only the ones
                # that never had one may receive it.
                super(ResCompany, unstamped).write(
                    dict(vals, timesheet_rounding_start_date=now)
                )
                remaining = self - unstamped
                return super(ResCompany, remaining).write(vals) if remaining else True
        return super().write(vals)

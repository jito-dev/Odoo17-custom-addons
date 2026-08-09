# -*- coding: utf-8 -*-

from odoo import models


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    def session_info(self):
        """Publish the tracking step so the grid view knows whether to re-read a cell.

        The grid patch needs to answer one question before it spends an RPC: can
        this cell's value have been changed by the server? Without the step in
        the session it would have to ask the server to find out, which is the
        very cost it is trying to avoid. Companies that leave rounding off get a
        `0` here and the patch does nothing at all.

        Internal users only — this is a timesheet setting and portal users have
        no grid to correct.
        """
        result = super().session_info()
        result['timesheet_rounding_step'] = (
            self.env.company._timesheet_rounding_minutes()
            if self.env.user._is_internal() else 0
        )
        return result

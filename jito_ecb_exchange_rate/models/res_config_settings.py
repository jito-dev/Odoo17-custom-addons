# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # Sync status (read-only display)
    ecb_last_sync_date = fields.Datetime(
        related='company_id.ecb_last_sync_date',
        readonly=True,
    )
    ecb_last_sync_status = fields.Selection(
        related='company_id.ecb_last_sync_status',
        readonly=True,
    )
    ecb_last_sync_error = fields.Char(
        related='company_id.ecb_last_sync_error',
        readonly=True,
    )

    # Configurable threshold
    ecb_stale_rate_days = fields.Integer(
        related='company_id.ecb_stale_rate_days',
        readonly=False,
    )

    def action_ecb_download_daily(self):
        """Proxy button in settings to trigger daily ECB download on current company."""
        return self.env.company.action_ecb_download_daily()

    def action_ecb_delete_all_rates(self):
        """Proxy button in settings to delete all currency rates for current company."""
        return self.env.company.action_ecb_delete_all_rates()

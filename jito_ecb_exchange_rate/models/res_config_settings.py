# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    def action_ecb_download_daily(self):
        """Proxy button in settings to trigger daily ECB download on current company."""
        return self.env.company.action_ecb_download_daily()

    def action_ecb_delete_all_rates(self):
        """Proxy button in settings to delete all currency rates for current company."""
        return self.env.company.action_ecb_delete_all_rates()

# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    fireflies_autopilot = fields.Boolean(
        related='company_id.fireflies_autopilot',
        readonly=False,
        string="Fireflies Autopilot",
    )

# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    fireflies_autopilot = fields.Boolean(
        related='company_id.fireflies_autopilot',
        readonly=False,
        string="Fireflies Autopilot",
    )

    fireflies_transcript_retention_days = fields.Integer(
        related='company_id.fireflies_transcript_retention_days',
        readonly=False,
        string="Transcript Retention (days)",
    )

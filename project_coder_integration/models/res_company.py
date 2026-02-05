# -*- coding: utf-8 -*-
from odoo import fields, models


class ResCompany(models.Model):
    """
    Inherits `res.company` to store company-wide settings
    for the Coder.com integration feature.
    """
    _inherit = 'res.company'

    coder_enabled = fields.Boolean(
        string="Enable Coder Integration",
        default=False,
        help="Enable integration with Coder.com workspaces for project tasks."
    )

    coder_api_token = fields.Char(
        string="Coder API Token",
        copy=False,
        help="Your Coder.com API session token. Generate from: https://coder.example.com/settings/tokens"
    )

    coder_base_url = fields.Char(
        string="Coder Base URL",
        copy=False,
        default="https://coder.jito.dev",
        help="Base URL for your Coder deployment (e.g., https://coder.jito.dev)"
    )

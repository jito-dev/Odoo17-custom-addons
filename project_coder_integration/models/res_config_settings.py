# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError
from .coder_api import CoderAPI


class ResConfigSettings(models.TransientModel):
    """
    Inherits `res.config.settings` to expose Coder integration
    settings in the main settings view.
    """
    _inherit = 'res.config.settings'

    coder_enabled = fields.Boolean(
        related='company_id.coder_enabled',
        string='Enable Coder Integration',
        readonly=False,
        help="Enable integration with Coder.com workspaces for project tasks."
    )

    coder_api_token = fields.Char(
        related='company_id.coder_api_token',
        string="Coder API Token",
        readonly=False,
        help="Your Coder.com API session token. Generate from your Coder settings."
    )

    coder_base_url = fields.Char(
        related='company_id.coder_base_url',
        string="Coder Base URL",
        readonly=False,
        help="Base URL for your Coder deployment (e.g., https://coder.jito.dev)"
    )

    def action_test_coder_connection(self):
        """
        Test the connection to Coder API using configured settings.
        Shows success or error message to the user.
        """
        self.ensure_one()

        if not self.coder_enabled:
            raise UserError("Please enable Coder Integration first.")

        if not self.coder_api_token:
            raise UserError("Please enter a Coder API Token.")

        if not self.coder_base_url:
            raise UserError("Please enter a Coder Base URL.")

        # Test connection
        api = CoderAPI(self.coder_base_url, self.coder_api_token)
        success, message, user_info = api.test_connection()

        if success:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Connection Successful',
                    'message': message,
                    'type': 'success',
                    'sticky': False,
                }
            }
        else:
            raise UserError(f"Connection failed: {message}")

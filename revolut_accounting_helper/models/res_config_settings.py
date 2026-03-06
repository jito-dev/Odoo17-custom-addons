from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    google_drive_client_id = fields.Char(
        string='Google Drive Client ID',
        config_parameter='google_drive_client_id',
    )
    google_drive_client_secret = fields.Char(
        string='Google Drive Client Secret',
        config_parameter='google_drive_client_secret',
    )

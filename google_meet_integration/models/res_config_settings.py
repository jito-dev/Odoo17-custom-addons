from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    google_meet_fallback_user_id = fields.Many2one(
        comodel_name='res.users',
        string='Google Meet Fallback User',
        config_parameter='google_meet_integration.fallback_user_id',
        domain=[('share', '=', False)],
        help="When an appointment's staff member has not connected their Google "
             "Calendar, this user's credentials will be used to mint the Meet link. "
             "Must be a Google Workspace account with Meet access.",
    )

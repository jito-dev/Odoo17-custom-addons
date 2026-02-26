from odoo import fields, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    google_drive_account_id = fields.Many2one(
        'google.drive.credentials',
        string='Google Drive Account',
    )

    _sql_constraints = [
        (
            'google_drive_account_uniq',
            'unique (google_drive_account_id)',
            "This Google Drive account is already linked to another user.",
        ),
    ]

    @property
    def SELF_READABLE_FIELDS(self):
        return super().SELF_READABLE_FIELDS + ['google_drive_account_id']

    @property
    def SELF_WRITEABLE_FIELDS(self):
        return super().SELF_WRITEABLE_FIELDS + ['google_drive_account_id']

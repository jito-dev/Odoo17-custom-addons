from odoo import fields, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    google_account_id = fields.Many2one(
        'google.credentials',
        string='Google Account (Gmail)',
    )

    _sql_constraints = [
        (
            'google_account_uniq',
            'unique (google_account_id)',
            "This Google account is already linked to another Odoo user.",
        ),
    ]

    @property
    def SELF_READABLE_FIELDS(self):
        return super().SELF_READABLE_FIELDS + ['google_account_id']

    @property
    def SELF_WRITEABLE_FIELDS(self):
        return super().SELF_WRITEABLE_FIELDS + ['google_account_id']

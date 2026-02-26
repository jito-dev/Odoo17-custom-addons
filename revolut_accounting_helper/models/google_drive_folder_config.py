from odoo import fields, models


class GoogleDriveFolderConfig(models.Model):
    """Stores the default Google Drive upload folder per Odoo user per Google account.

    This allows each Google account (email) to maintain its own default folder
    independently. Switching or disconnecting a Google account does not lose the
    saved folder for any other account – the config record persists keyed by
    (user_id, google_email).
    """

    _name = 'google.drive.folder.config'
    _description = 'Default Google Drive folder per Google account'

    user_id = fields.Many2one(
        'res.users',
        string='Odoo User',
        required=True,
        ondelete='cascade',
        index=True,
    )
    google_email = fields.Char('Google Email', required=True)
    default_folder = fields.Char('Default Upload Folder')

    _sql_constraints = [
        (
            'user_email_uniq',
            'unique(user_id, google_email)',
            'A default folder config already exists for this user and Google account.',
        ),
    ]

    @classmethod
    def _get_default_folder(cls, env, user_id, google_email):
        """Return the saved default folder for (user_id, google_email), or False."""
        if not google_email:
            return False
        record = env['google.drive.folder.config'].sudo().search(
            [('user_id', '=', user_id), ('google_email', '=', google_email)],
            limit=1,
        )
        return record.default_folder or False

    @classmethod
    def _save_default_folder(cls, env, user_id, google_email, folder):
        """Upsert the default folder for (user_id, google_email)."""
        if not google_email:
            return
        existing = env['google.drive.folder.config'].sudo().search(
            [('user_id', '=', user_id), ('google_email', '=', google_email)],
            limit=1,
        )
        if existing:
            existing.default_folder = folder
        else:
            env['google.drive.folder.config'].sudo().create({
                'user_id': user_id,
                'google_email': google_email,
                'default_folder': folder,
            })

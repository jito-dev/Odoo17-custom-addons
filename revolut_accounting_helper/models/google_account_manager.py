from werkzeug import urls as werkzeug_urls

from odoo import api, fields, models, _
from odoo.exceptions import UserError

GOOGLE_AUTH_ENDPOINT = 'https://accounts.google.com/o/oauth2/auth'
# Request Drive access + email so the Account Manager can display who is signed in
GOOGLE_ACCOUNT_SCOPES = ' '.join([
    'https://www.googleapis.com/auth/drive.file',
    'https://www.googleapis.com/auth/userinfo.email',
])


class GoogleAccountManager(models.TransientModel):
    _name = 'google.account.manager'
    _description = 'Google Account Manager'

    is_connected = fields.Boolean(string='Connected', default=False)
    google_email = fields.Char(string='Google Account', readonly=True)

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        user = self.env.user
        creds = user.sudo().google_drive_account_id
        if creds and creds._is_authorized():
            defaults['is_connected'] = True
            defaults['google_email'] = creds.sudo().google_email or ''
        else:
            defaults['is_connected'] = False
            defaults['google_email'] = False
        return defaults

    def _reload_action(self):
        """Return an action that re-opens the Account Manager with a fresh record."""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Account Manager',
            'res_model': self._name,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_connect_google(self):
        """Open the Google OAuth consent screen in a new browser tab."""
        self.ensure_one()
        get_param = self.env['ir.config_parameter'].sudo().get_param
        client_id = get_param('google_drive_client_id')
        if not client_id:
            raise UserError(_(
                "Google Drive is not configured. "
                "Please ask your administrator to set the Client ID and Secret in Settings."
            ))
        base_url = get_param('web.base.url').rstrip('/')
        redirect_uri = f'{base_url}/google/drive/callback'
        params = {
            'response_type': 'code',
            'client_id': client_id,
            'scope': GOOGLE_ACCOUNT_SCOPES,
            'redirect_uri': redirect_uri,
            'access_type': 'offline',
            'prompt': 'consent',
        }
        auth_url = f'{GOOGLE_AUTH_ENDPOINT}?{werkzeug_urls.url_encode(params)}'
        return {
            'type': 'ir.actions.act_url',
            'url': auth_url,
            'target': 'new',
        }

    def action_refresh(self):
        """Reload the Account Manager to reflect the latest connection state."""
        return self._reload_action()

    def action_disconnect_google(self):
        """Disconnect the Google account without logging out of Odoo."""
        user = self.env.user
        creds = user.sudo().google_drive_account_id
        if creds:
            creds.disconnect()
        return self._reload_action()

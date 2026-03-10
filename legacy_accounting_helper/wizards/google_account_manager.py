import urllib.parse

from odoo import api, fields, models, _
from odoo.exceptions import UserError

GOOGLE_AUTH_ENDPOINT = 'https://accounts.google.com/o/oauth2/auth'
GOOGLE_GMAIL_SCOPES = ' '.join([
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/userinfo.email',
])


class GoogleAccountManager(models.TransientModel):
    _name = 'google.account.manager'
    _description = 'Google Account Manager (Gmail)'

    is_connected = fields.Boolean(string='Connected', default=False)
    google_email = fields.Char(string='Google Account', readonly=True)
    client_id = fields.Char(string='OAuth Client ID')
    client_secret = fields.Char(string='OAuth Client Secret')

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        get_param = self.env['ir.config_parameter'].sudo().get_param
        defaults['client_id'] = get_param('google_gmail_client_id') or ''
        defaults['client_secret'] = get_param('google_gmail_client_secret') or ''

        user = self.env.user
        creds = user.sudo().google_account_id
        if creds and creds._is_authorized():
            defaults['is_connected'] = True
            defaults['google_email'] = creds.sudo().google_email or ''
        else:
            defaults['is_connected'] = False
            defaults['google_email'] = False
        return defaults

    def _reload_action(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Google / Gmail Setup',
            'res_model': self._name,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_save_credentials(self):
        """Persist the Client ID and Secret in system parameters."""
        self.ensure_one()
        set_param = self.env['ir.config_parameter'].sudo().set_param
        set_param('google_gmail_client_id', (self.client_id or '').strip())
        set_param('google_gmail_client_secret', (self.client_secret or '').strip())
        return self._reload_action()

    def action_connect_google(self):
        """Save credentials (if changed) then open the Google OAuth consent screen."""
        self.ensure_one()
        # Auto-save credentials if filled in
        if self.client_id or self.client_secret:
            self.action_save_credentials()

        get_param = self.env['ir.config_parameter'].sudo().get_param
        client_id = get_param('google_gmail_client_id')
        if not client_id:
            raise UserError(_(
                "Please enter your OAuth Client ID and click Save first."
            ))
        base_url = get_param('web.base.url').rstrip('/')
        redirect_uri = f'{base_url}/google/gmail/callback'
        params = urllib.parse.urlencode({
            'response_type': 'code',
            'client_id': client_id,
            'scope': GOOGLE_GMAIL_SCOPES,
            'redirect_uri': redirect_uri,
            'access_type': 'offline',
            'prompt': 'consent',
        })
        auth_url = f'{GOOGLE_AUTH_ENDPOINT}?{params}'
        return {
            'type': 'ir.actions.act_url',
            'url': auth_url,
            'target': 'new',
        }

    def action_refresh(self):
        """Reload the wizard to reflect the latest connection state."""
        return self._reload_action()

    def action_disconnect_google(self):
        """Disconnect the Google account."""
        self.ensure_one()
        user = self.env.user
        creds = user.sudo().google_account_id
        if creds:
            creds.disconnect()
        return self._reload_action()

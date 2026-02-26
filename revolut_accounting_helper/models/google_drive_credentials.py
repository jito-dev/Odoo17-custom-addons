import logging
import requests
from datetime import timedelta

from odoo import fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

GOOGLE_TOKEN_ENDPOINT = 'https://accounts.google.com/o/oauth2/token'


class GoogleDriveCredentials(models.Model):
    _name = 'google.drive.credentials'
    _description = 'Google Drive OAuth2 Credentials'

    user_ids = fields.One2many('res.users', 'google_drive_account_id', required=True)
    access_token = fields.Char('Access Token', copy=False)
    refresh_token = fields.Char('Refresh Token', copy=False)
    token_expiry = fields.Datetime('Token Expiry', copy=False)
    default_folder = fields.Char('Default Upload Folder', copy=False)

    def _is_authorized(self):
        self.ensure_one()
        return bool(self.sudo().refresh_token)

    def _is_token_valid(self):
        self.ensure_one()
        return (
            self.token_expiry
            and self.token_expiry >= (fields.Datetime.now() + timedelta(minutes=1))
        )

    def set_tokens(self, access_token, refresh_token, ttl):
        self.write({
            'access_token': access_token,
            'refresh_token': refresh_token,
            'token_expiry': fields.Datetime.now() + timedelta(seconds=ttl) if ttl else False,
        })

    def _get_valid_access_token(self):
        self.ensure_one()
        if not self._is_authorized():
            raise UserError(_(
                "Google Drive account is not authorized. "
                "Please connect your Google Drive account via the Upload wizard."
            ))
        if not self._is_token_valid():
            self._refresh_access_token()
        return self.sudo().access_token

    def _refresh_access_token(self):
        self.ensure_one()
        get_param = self.env['ir.config_parameter'].sudo().get_param
        client_id = get_param('google_drive_client_id')
        client_secret = get_param('google_drive_client_secret')

        if not client_id or not client_secret:
            raise UserError(_(
                "Google Drive OAuth2 credentials are not configured. "
                "Please configure Client ID and Secret in Settings."
            ))

        headers = {"content-type": "application/x-www-form-urlencoded"}
        data = {
            'refresh_token': self.sudo().refresh_token,
            'client_id': client_id,
            'client_secret': client_secret,
            'grant_type': 'refresh_token',
        }

        try:
            response = requests.post(GOOGLE_TOKEN_ENDPOINT, data=data, headers=headers, timeout=10)
            response.raise_for_status()
            resp_json = response.json()
            ttl = resp_json.get('expires_in')
            self.write({
                'access_token': resp_json.get('access_token'),
                'token_expiry': fields.Datetime.now() + timedelta(seconds=ttl) if ttl else False,
            })
        except requests.HTTPError as error:
            if error.response.status_code in (400, 401):
                self.env.cr.rollback()
                self.set_tokens(False, False, 0)
                self.env.cr.commit()
            error_key = error.response.json().get("error", "unknown")
            raise UserError(_(
                "Failed to refresh Google Drive access token [%s]. "
                "Please reconnect your Google Drive account.", error_key
            ))

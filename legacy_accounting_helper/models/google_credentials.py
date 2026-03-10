import logging
import urllib.parse
import urllib.request
import urllib.error
import json
from datetime import timedelta

from odoo import fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

GOOGLE_TOKEN_ENDPOINT = 'https://oauth2.googleapis.com/token'


class GoogleCredentials(models.Model):
    _name = 'google.credentials'
    _description = 'Google OAuth2 Credentials (Gmail)'

    user_ids = fields.One2many('res.users', 'google_account_id', string='Users')
    access_token = fields.Char('Access Token', copy=False)
    refresh_token = fields.Char('Refresh Token', copy=False)
    token_expiry = fields.Datetime('Token Expiry', copy=False)
    google_email = fields.Char('Google Account Email', copy=False)

    def _is_authorized(self):
        self.ensure_one()
        return bool(self.sudo().refresh_token)

    def _is_token_valid(self):
        self.ensure_one()
        return (
            self.token_expiry
            and self.token_expiry >= (fields.Datetime.now() + timedelta(minutes=1))
        )

    def set_tokens(self, access_token, refresh_token, ttl, google_email=None):
        vals = {
            'access_token': access_token,
            'refresh_token': refresh_token,
            'token_expiry': fields.Datetime.now() + timedelta(seconds=ttl) if ttl else False,
        }
        if google_email is not None:
            vals['google_email'] = google_email
        self.write(vals)

    def disconnect(self):
        """Clear all OAuth tokens and email, effectively disconnecting the Google account."""
        self.ensure_one()
        self.sudo().write({
            'access_token': False,
            'refresh_token': False,
            'token_expiry': False,
            'google_email': False,
        })

    def _get_valid_access_token(self):
        self.ensure_one()
        if not self._is_authorized():
            raise UserError(_(
                "Google account is not authorized. "
                "Please connect your Google account via Google / Gmail Setup."
            ))
        if not self._is_token_valid():
            self._refresh_access_token()
        return self.sudo().access_token

    def _refresh_access_token(self):
        self.ensure_one()
        get_param = self.env['ir.config_parameter'].sudo().get_param
        client_id = get_param('google_gmail_client_id')
        client_secret = get_param('google_gmail_client_secret')

        if not client_id or not client_secret:
            raise UserError(_(
                "Google OAuth2 credentials are not configured. "
                "Please enter Client ID and Secret in Google / Gmail Setup."
            ))

        data = urllib.parse.urlencode({
            'refresh_token': self.sudo().refresh_token,
            'client_id': client_id,
            'client_secret': client_secret,
            'grant_type': 'refresh_token',
        }).encode()

        req = urllib.request.Request(
            GOOGLE_TOKEN_ENDPOINT,
            data=data,
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
            method='POST',
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                resp_json = json.loads(resp.read().decode())
            ttl = resp_json.get('expires_in')
            self.write({
                'access_token': resp_json.get('access_token'),
                'token_expiry': fields.Datetime.now() + timedelta(seconds=ttl) if ttl else False,
            })
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            try:
                error_key = json.loads(body).get('error', 'unknown')
            except Exception:
                error_key = body[:100]
            if e.code in (400, 401):
                self.sudo().write({
                    'access_token': False,
                    'refresh_token': False,
                    'token_expiry': False,
                })
            raise UserError(_(
                "Failed to refresh Google access token [%s]. "
                "Please reconnect your Google account.", error_key
            ))
        except Exception as e:
            raise UserError(_("Failed to refresh Google access token: %s", str(e)))

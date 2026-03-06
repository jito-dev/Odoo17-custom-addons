import base64
import logging
import urllib.parse

import requests
from werkzeug import urls

from odoo import Command, http
from odoo.http import request

_logger = logging.getLogger(__name__)

GOOGLE_TOKEN_ENDPOINT = 'https://accounts.google.com/o/oauth2/token'

_SUCCESS_HTML = """<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Google Account Connected</title></head>
<body style="font-family:sans-serif;text-align:center;padding:60px">
  <h2 style="color:#28a745">&#10003; Google account connected successfully!</h2>
  <p>You can close this tab and return to Odoo.</p>
  <script>
    try {{ window.opener && window.opener.postMessage('google_drive_connected', '*'); }} catch(e) {{}}
    setTimeout(function(){{ window.close(); }}, 2000);
  </script>
</body>
</html>"""

_ERROR_HTML = """<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Connection Error</title></head>
<body style="font-family:sans-serif;text-align:center;padding:60px">
  <h2 style="color:#dc3545">&#10007; Google account connection failed</h2>
  <p>{error}</p>
  <p>Please close this tab and try again.</p>
</body>
</html>"""


class GoogleDriveAuthController(http.Controller):

    @http.route('/google/drive/callback', type='http', auth='user')
    def google_drive_callback(self, code=None, error=None, **kwargs):
        """Handle Google OAuth2 callback: exchange code for tokens and store them."""
        if error:
            _logger.warning("Google Drive OAuth error: %s", error)
            return request.make_response(
                _ERROR_HTML.format(error=error),
                headers=[('Content-Type', 'text/html; charset=utf-8')],
            )

        if not code:
            return request.make_response(
                _ERROR_HTML.format(error='No authorization code received.'),
                headers=[('Content-Type', 'text/html; charset=utf-8')],
            )

        get_param = request.env['ir.config_parameter'].sudo().get_param
        client_id = get_param('google_drive_client_id')
        client_secret = get_param('google_drive_client_secret')

        if not client_id or not client_secret:
            return request.make_response(
                _ERROR_HTML.format(error='OAuth credentials are not configured on this server.'),
                headers=[('Content-Type', 'text/html; charset=utf-8')],
            )

        # Must match exactly what was sent in the authorization request
        base_url = get_param('web.base.url').rstrip('/')
        redirect_uri = f'{base_url}/google/drive/callback'

        headers = {"content-type": "application/x-www-form-urlencoded"}
        data = {
            'code': code,
            'client_id': client_id,
            'client_secret': client_secret,
            'redirect_uri': redirect_uri,
            'grant_type': 'authorization_code',
        }

        try:
            resp = requests.post(GOOGLE_TOKEN_ENDPOINT, data=data, headers=headers, timeout=10)
            resp.raise_for_status()
            tokens = resp.json()
        except requests.HTTPError as exc:
            try:
                error_msg = exc.response.json().get('error_description', str(exc))
            except Exception:
                error_msg = str(exc)
            _logger.error("Google Drive token exchange failed: %s", error_msg)
            return request.make_response(
                _ERROR_HTML.format(error=error_msg),
                headers=[('Content-Type', 'text/html; charset=utf-8')],
            )
        except Exception:
            _logger.exception("Unexpected error during Google Drive token exchange")
            return request.make_response(
                _ERROR_HTML.format(error='An unexpected error occurred. Please try again.'),
                headers=[('Content-Type', 'text/html; charset=utf-8')],
            )

        access_token = tokens.get('access_token')
        refresh_token = tokens.get('refresh_token')
        ttl = tokens.get('expires_in', 3600)

        if not refresh_token:
            _logger.warning("Google Drive OAuth2: no refresh_token received.")

        # Try to fetch the Google account email using the userinfo endpoint
        google_email = None
        try:
            userinfo_resp = requests.get(
                'https://www.googleapis.com/oauth2/v3/userinfo',
                headers={'Authorization': f'Bearer {access_token}'},
                timeout=10,
            )
            if userinfo_resp.status_code == 200:
                google_email = userinfo_resp.json().get('email')
        except Exception:
            _logger.warning("Could not fetch Google user info after OAuth.", exc_info=True)

        user = request.env.user
        creds = user.sudo().google_drive_account_id
        if not creds:
            creds = request.env['google.drive.credentials'].sudo().create(
                {'user_ids': [Command.set([user.id])]}
            )
        creds.set_tokens(access_token, refresh_token, ttl, google_email=google_email)

        return request.make_response(
            _SUCCESS_HTML,
            headers=[('Content-Type', 'text/html; charset=utf-8')],
        )

    # ── Gmail attachment on-demand download ───────────────────────────────────

    @http.route(
        '/gmail/attachment/download/<int:attachment_id>',
        type='http', auth='user', methods=['GET'],
    )
    def gmail_attachment_download(self, attachment_id, **kwargs):
        """Fetch a Gmail attachment on demand and stream it as a file download."""
        env = request.env

        att = env['google.gmail.search.attachment'].sudo().browse(attachment_id)
        if not att.exists():
            return request.not_found()

        # Security: the wizard that owns this attachment must belong to the current user
        wizard = att.result_id.wizard_id
        if not wizard.exists() or wizard.create_uid.id != env.uid:
            return request.not_found()

        if not att.gmail_attachment_id or not att.gmail_message_id:
            return request.not_found()

        try:
            service = wizard._get_gmail_service()
            att_response = service.users().messages().attachments().get(
                userId='me',
                messageId=att.gmail_message_id,
                id=att.gmail_attachment_id,
            ).execute()
        except Exception as exc:
            _logger.error("Gmail attachment download failed (att_id=%s): %s", attachment_id, exc)
            return request.not_found()

        raw_data = att_response.get('data', '')
        padded = raw_data + '=' * (-len(raw_data) % 4)
        file_bytes = base64.urlsafe_b64decode(padded)

        mime_type = att.mime_type or 'application/octet-stream'
        filename = att.name or 'attachment'

        # RFC 5987 encoding for filenames that may contain non-ASCII characters
        # (e.g. Cyrillic, accented letters) — plain HTTP headers only allow ASCII
        filename_encoded = urllib.parse.quote(filename.encode('utf-8'), safe='')
        content_disposition = (
            f"attachment; "
            f"filename=\"{filename.encode('ascii', errors='replace').decode('ascii')}\"; "
            f"filename*=UTF-8''{filename_encoded}"
        )

        return request.make_response(
            file_bytes,
            headers=[
                ('Content-Type', mime_type),
                ('Content-Disposition', content_disposition),
                ('Content-Length', str(len(file_bytes))),
            ],
        )

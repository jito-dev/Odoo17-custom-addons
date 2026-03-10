import base64
import json
import logging
import urllib.parse
import urllib.request
import urllib.error

from odoo import Command, http
from odoo.http import request

_logger = logging.getLogger(__name__)

GOOGLE_TOKEN_ENDPOINT = 'https://oauth2.googleapis.com/token'

_SUCCESS_HTML = """<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Google Account Connected</title></head>
<body style="font-family:sans-serif;text-align:center;padding:60px">
  <h2 style="color:#28a745">&#10003; Google account connected successfully!</h2>
  <p>You can close this tab and return to Odoo.</p>
  <script>
    try {{ window.opener && window.opener.postMessage('google_gmail_connected', '*'); }} catch(e) {{}}
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


class GoogleGmailAuthController(http.Controller):

    @http.route('/google/gmail/callback', type='http', auth='user')
    def google_gmail_callback(self, code=None, error=None, **kwargs):
        """Handle Google OAuth2 callback: exchange code for tokens and store them."""
        if error:
            _logger.warning("Google Gmail OAuth error: %s", error)
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
        client_id = get_param('google_gmail_client_id')
        client_secret = get_param('google_gmail_client_secret')

        if not client_id or not client_secret:
            return request.make_response(
                _ERROR_HTML.format(error='OAuth credentials are not configured on this server.'),
                headers=[('Content-Type', 'text/html; charset=utf-8')],
            )

        base_url = get_param('web.base.url').rstrip('/')
        redirect_uri = f'{base_url}/google/gmail/callback'

        post_data = urllib.parse.urlencode({
            'code': code,
            'client_id': client_id,
            'client_secret': client_secret,
            'redirect_uri': redirect_uri,
            'grant_type': 'authorization_code',
        }).encode()

        req = urllib.request.Request(
            GOOGLE_TOKEN_ENDPOINT,
            data=post_data,
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
            method='POST',
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                tokens = json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            body = exc.read().decode()
            try:
                error_msg = json.loads(body).get('error_description', body)
            except Exception:
                error_msg = body[:200]
            _logger.error("Google Gmail token exchange failed: %s", error_msg)
            return request.make_response(
                _ERROR_HTML.format(error=error_msg),
                headers=[('Content-Type', 'text/html; charset=utf-8')],
            )
        except Exception:
            _logger.exception("Unexpected error during Google Gmail token exchange")
            return request.make_response(
                _ERROR_HTML.format(error='An unexpected error occurred. Please try again.'),
                headers=[('Content-Type', 'text/html; charset=utf-8')],
            )

        access_token = tokens.get('access_token')
        refresh_token = tokens.get('refresh_token')
        ttl = tokens.get('expires_in', 3600)

        if not refresh_token:
            _logger.warning("Google Gmail OAuth2: no refresh_token received.")

        # Fetch the Google account email via userinfo endpoint
        google_email = None
        try:
            info_req = urllib.request.Request(
                'https://www.googleapis.com/oauth2/v3/userinfo',
                headers={'Authorization': f'Bearer {access_token}'},
            )
            with urllib.request.urlopen(info_req, timeout=10) as resp:
                if resp.status == 200:
                    google_email = json.loads(resp.read().decode()).get('email')
        except Exception:
            _logger.warning("Could not fetch Google user info after OAuth.", exc_info=True)

        user = request.env.user
        creds = user.sudo().google_account_id
        if not creds:
            creds = request.env['google.credentials'].sudo().create(
                {'user_ids': [Command.set([user.id])]}
            )
            user.sudo().write({'google_account_id': creds.id})
        creds.set_tokens(access_token, refresh_token, ttl, google_email=google_email)

        return request.make_response(
            _SUCCESS_HTML,
            headers=[('Content-Type', 'text/html; charset=utf-8')],
        )

    # ── Gmail attachment preview / download ───────────────────────────────────

    @http.route(
        '/revolut/gmail/attachment/preview/<int:att_id>',
        type='http', auth='user', methods=['GET'],
    )
    def gmail_attachment_preview(self, att_id, **kwargs):
        """Stream a Gmail attachment directly to the browser for preview/download."""
        env = request.env
        att = env['revolut.gmail.attachment'].browse(att_id)
        if not att.exists():
            return request.not_found()

        # Security: only the owner of the linked transaction (same user) may preview
        if att.transaction_id.create_uid.id != env.uid and not env.user._is_admin():
            return request.not_found()

        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
        except ImportError:
            return request.make_response(
                'Google API libraries not installed.',
                headers=[('Content-Type', 'text/plain')],
            )

        creds_record = env.user.sudo().google_account_id
        if not creds_record or not creds_record._is_authorized():
            return request.make_response(
                'Google account not connected.',
                headers=[('Content-Type', 'text/plain')],
            )

        get_param = env['ir.config_parameter'].sudo().get_param
        access_token = creds_record._get_valid_access_token()
        creds = Credentials(
            token=access_token,
            refresh_token=creds_record.sudo().refresh_token,
            token_uri='https://oauth2.googleapis.com/token',
            client_id=get_param('google_gmail_client_id'),
            client_secret=get_param('google_gmail_client_secret'),
            scopes=['https://www.googleapis.com/auth/gmail.readonly'],
        )

        try:
            service = build('gmail', 'v1', credentials=creds)
            att_response = service.users().messages().attachments().get(
                userId='me',
                messageId=att.gmail_message_id,
                id=att.gmail_attachment_id,
            ).execute()
        except Exception as exc:
            _logger.error("Gmail attachment preview failed (att_id=%s): %s", att_id, exc)
            return request.not_found()

        raw_data = att_response.get('data', '')
        padded = raw_data + '=' * (-len(raw_data) % 4)
        file_bytes = base64.urlsafe_b64decode(padded)

        mime_type = att.mime_type or 'application/octet-stream'
        filename = att.name or 'attachment'
        filename_encoded = urllib.parse.quote(filename.encode('utf-8'), safe='')
        filename_ascii = filename.encode('ascii', errors='replace').decode('ascii')

        # Inline for viewable types (PDF, images); attachment for everything else
        viewable = mime_type.startswith('image/') or mime_type == 'application/pdf'
        disposition = 'inline' if viewable else 'attachment'
        content_disposition = (
            f'{disposition}; '
            f'filename="{filename_ascii}"; '
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

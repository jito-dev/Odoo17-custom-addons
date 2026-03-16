import json
import logging
import urllib.parse
import urllib.request
import urllib.error

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

UPWORK_TOKEN_ENDPOINT = 'https://www.upwork.com/api/v3/oauth2/token'

_SUCCESS_HTML = """<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Upwork Connected</title></head>
<body style="font-family:sans-serif;text-align:center;padding:60px">
  <h2 style="color:#28a745">&#10003; Upwork account connected successfully!</h2>
  <p>You can close this tab and return to Odoo.</p>
  <script>
    try {{ window.opener && window.opener.postMessage('upwork_connected', '*'); }} catch(e) {{}}
    setTimeout(function(){{ window.close(); }}, 2000);
  </script>
</body>
</html>"""

_ERROR_HTML = """<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Connection Error</title></head>
<body style="font-family:sans-serif;text-align:center;padding:60px">
  <h2 style="color:#dc3545">&#10007; Upwork connection failed</h2>
  <p>{error}</p>
  <p>Please close this tab and try again.</p>
</body>
</html>"""


class UpworkOAuthController(http.Controller):

    @http.route('/upwork/callback', type='http', auth='user')
    def upwork_callback(self, code=None, error=None, **kwargs):
        """Handle Upwork OAuth2 callback: exchange authorization code for tokens."""
        if error:
            _logger.warning("Upwork OAuth error: %s", error)
            return request.make_response(
                _ERROR_HTML.format(error=error),
                headers=[('Content-Type', 'text/html; charset=utf-8')],
            )

        if not code:
            return request.make_response(
                _ERROR_HTML.format(error='No authorization code received.'),
                headers=[('Content-Type', 'text/html; charset=utf-8')],
            )

        settings = request.env['usa.settings'].sudo()._get_singleton()
        client_id = settings.upwork_key
        client_secret = settings.upwork_secret
        callback_url = settings.callback_url

        if not client_id or not client_secret:
            return request.make_response(
                _ERROR_HTML.format(error='Upwork API credentials are not configured.'),
                headers=[('Content-Type', 'text/html; charset=utf-8')],
            )

        post_data = urllib.parse.urlencode({
            'code': code,
            'client_id': client_id,
            'client_secret': client_secret,
            'redirect_uri': callback_url,
            'grant_type': 'authorization_code',
        }).encode()

        req = urllib.request.Request(
            UPWORK_TOKEN_ENDPOINT,
            data=post_data,
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
            method='POST',
        )

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                tokens = json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            body = exc.read().decode()
            try:
                error_msg = json.loads(body).get('error_description', body)
            except Exception:
                error_msg = body[:300]
            _logger.error("Upwork token exchange failed: %s", error_msg)
            return request.make_response(
                _ERROR_HTML.format(error=error_msg),
                headers=[('Content-Type', 'text/html; charset=utf-8')],
            )
        except Exception:
            _logger.exception("Unexpected error during Upwork token exchange")
            return request.make_response(
                _ERROR_HTML.format(error='An unexpected error occurred. Please try again.'),
                headers=[('Content-Type', 'text/html; charset=utf-8')],
            )

        from odoo import fields as odoo_fields
        from datetime import timedelta

        access_token = tokens.get('access_token')
        refresh_token = tokens.get('refresh_token')
        ttl = tokens.get('expires_in', 3600)

        if not access_token:
            return request.make_response(
                _ERROR_HTML.format(error='No access token returned by Upwork.'),
                headers=[('Content-Type', 'text/html; charset=utf-8')],
            )

        expiry = odoo_fields.Datetime.now() + timedelta(seconds=int(ttl)) if ttl else False

        settings.write({
            'access_token': access_token,
            'refresh_token': refresh_token or False,
            'token_expiry': expiry,
        })

        _logger.info("Upwork OAuth2: tokens stored successfully for user %s", request.env.user.login)

        # Auto-load organizations (and accounting entity for single-org accounts)
        # immediately so the user sees a ready form after the popup closes.
        try:
            settings.action_load_organizations()
        except Exception as exc:
            _logger.warning("Upwork OAuth2: auto-load organizations failed: %s", exc)

        return request.make_response(
            _SUCCESS_HTML,
            headers=[('Content-Type', 'text/html; charset=utf-8')],
        )

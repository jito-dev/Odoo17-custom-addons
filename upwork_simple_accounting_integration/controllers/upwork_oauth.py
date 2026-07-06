import html
import json
import logging
import urllib.parse
import urllib.request
import urllib.error

from odoo import http
from odoo.http import request

from odoo.addons.upwork_simple_accounting_integration.models.usa_settings import (
    upwork_request, _upwork_proxy,
)

_logger = logging.getLogger(__name__)


def _fail(error):
    """Render the OAuth failure page showing the ACTUAL error (HTML-escaped)."""
    return request.make_response(
        _ERROR_HTML.format(error=html.escape(str(error) or 'Unknown error')),
        headers=[('Content-Type', 'text/html; charset=utf-8')],
    )

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
            description = kwargs.get('error_description') or kwargs.get('error_uri') or ''
            full = '%s — %s' % (error, description) if description else error
            _logger.warning("Upwork OAuth error: %s", full)
            return _fail(full)

        if not code:
            return _fail('No authorization code received from Upwork.')

        settings = request.env['usa.settings'].sudo()._get_singleton()
        client_id = settings.upwork_key
        client_secret = settings.upwork_secret
        callback_url = settings.callback_url

        if not client_id or not client_secret:
            return _fail('Upwork API credentials (key/secret) are not configured in Settings.')

        post_data = urllib.parse.urlencode({
            'code': code,
            'client_id': client_id,
            'client_secret': client_secret,
            'redirect_uri': callback_url,
            'grant_type': 'authorization_code',
        }).encode()

        # Route through the shared helper, which impersonates a browser TLS
        # fingerprint (curl_cffi) to get past Upwork's Cloudflare bot protection.
        try:
            status, body = upwork_request(
                UPWORK_TOKEN_ENDPOINT,
                post_data,
                headers={
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'Accept': 'application/json',
                },
                timeout=20,
                proxy=_upwork_proxy(request.env),
            )
        except Exception as exc:
            _logger.exception("Unexpected error during Upwork token exchange")
            return _fail('%s: %s' % (type(exc).__name__, exc))

        if status != 200:
            try:
                parsed = json.loads(body)
                detail = parsed.get('error_description') or parsed.get('error') or body
            except Exception:
                detail = body[:500]
            error_msg = 'Token exchange failed (HTTP %s): %s' % (status, detail)
            _logger.error("Upwork token exchange failed: %s", error_msg)
            return _fail(error_msg)

        try:
            tokens = json.loads(body)
        except Exception:
            return _fail('Upwork returned a non-JSON response: %s' % body[:500])

        from odoo import fields as odoo_fields
        from datetime import timedelta

        access_token = tokens.get('access_token')
        refresh_token = tokens.get('refresh_token')
        ttl = tokens.get('expires_in', 3600)

        if not access_token:
            return _fail('No access token returned by Upwork. Response: %s' % json.dumps(tokens)[:500])

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

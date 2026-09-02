import json
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.upwork_simple_accounting_integration.models import usa_settings

PATH = ('odoo.addons.upwork_simple_accounting_integration.models'
        '.usa_settings.upwork_request')


@tagged('post_install', '-at_install')
class TestTokenRefresh(TransactionCase):
    """Covers the refresh defects behind 'the Upwork token dies after a week'."""

    def setUp(self):
        super().setUp()
        self.settings = self.env['usa.settings'].sudo()._get_singleton()
        self.settings.write({
            'upwork_key': 'key',
            'upwork_secret': 'secret',
            'access_token': 'old-access',
            'refresh_token': 'old-refresh',
            'token_expiry': fields.Datetime.now() - timedelta(minutes=5),
        })

    def _token_response(self, **extra):
        payload = {'access_token': 'new-access', 'expires_in': 86400}
        payload.update(extra)
        return 200, json.dumps(payload)

    # ── A. rotation ──────────────────────────────────────────────────────────

    def test_rotated_refresh_token_is_stored(self):
        """A refresh token returned by Upwork replaces the stored one — without
        this the *second* refresh fails with 400."""
        with patch(PATH, return_value=self._token_response(refresh_token='new-refresh')):
            self.assertTrue(self.settings._refresh_access_token())
        self.assertEqual(self.settings.refresh_token, 'new-refresh')
        self.assertEqual(self.settings.access_token, 'new-access')
        self.assertTrue(self.settings.token_last_refresh)
        self.assertFalse(self.settings.token_last_error)

    def test_missing_refresh_token_in_response_keeps_the_old_one(self):
        """Upwork not rotating must not blank the field either."""
        with patch(PATH, return_value=self._token_response()):
            self.settings._refresh_access_token()
        self.assertEqual(self.settings.refresh_token, 'old-refresh')

    def test_expiry_uses_the_returned_ttl(self):
        with patch(PATH, return_value=self._token_response(expires_in=120)):
            self.settings._refresh_access_token()
        delta = self.settings.token_expiry - fields.Datetime.now()
        self.assertLess(abs(delta.total_seconds() - 120), 30)

    # ── B. transient vs fatal ────────────────────────────────────────────────

    def test_cloudflare_html_400_does_not_wipe_tokens(self):
        """A 400 with an HTML body is a proxy/Cloudflare failure, not a dead
        grant — burning the refresh token there costs a manual reconnect."""
        with patch(PATH, return_value=(400, '<html>error 1020</html>')):
            with self.assertRaises(UserError):
                self.settings._refresh_access_token()
        self.assertEqual(self.settings.refresh_token, 'old-refresh')
        self.assertEqual(self.settings.access_token, 'old-access')

    def test_server_error_does_not_wipe_tokens(self):
        with patch(PATH, return_value=(503, 'upstream unavailable')):
            with self.assertRaises(UserError):
                self.settings._refresh_access_token()
        self.assertEqual(self.settings.refresh_token, 'old-refresh')

    def test_network_exception_does_not_wipe_tokens(self):
        with patch(PATH, side_effect=OSError('proxy down')):
            with self.assertRaises(UserError):
                self.settings._refresh_access_token()
        self.assertEqual(self.settings.refresh_token, 'old-refresh')

    def test_invalid_grant_wipes_tokens(self):
        """The one case where the grant really is dead.

        Asserted through the non-raising path on purpose: `assertRaises` opens a
        savepoint and rolls back everything written inside it, which would hide
        the very write this test is about.
        """
        body = json.dumps({'error': 'invalid_grant',
                           'error_description': 'refresh token expired'})
        with patch(PATH, return_value=(400, body)):
            self.assertFalse(self.settings._refresh_access_token(raise_on_failure=False))
        self.assertFalse(self.settings.refresh_token)
        self.assertFalse(self.settings.access_token)
        self.assertFalse(self.settings.token_expiry)

    def test_invalid_grant_raises_on_the_interactive_path(self):
        body = json.dumps({'error': 'invalid_grant'})
        with patch(PATH, return_value=(400, body)):
            with self.assertRaises(UserError):
                self.settings._refresh_access_token()

    def test_invalid_client_keeps_tokens(self):
        """Wrong key/secret says nothing about the refresh token."""
        body = json.dumps({'error': 'invalid_client'})
        with patch(PATH, return_value=(401, body)):
            self.assertFalse(self.settings._refresh_access_token(raise_on_failure=False))
        self.assertEqual(self.settings.refresh_token, 'old-refresh')
        self.assertEqual(self.settings.access_token, 'old-access')

    # ── E. background path ───────────────────────────────────────────────────

    def test_background_refresh_returns_false_instead_of_raising(self):
        with patch(PATH, return_value=(503, 'boom')):
            self.assertFalse(self.settings._refresh_access_token(raise_on_failure=False))
        self.assertTrue(self.settings.token_last_error)

    def test_dead_grant_posts_one_chatter_message(self):
        body = json.dumps({'error': 'invalid_grant'})
        before = len(self.settings.message_ids)
        with patch(PATH, return_value=(400, body)):
            self.settings._refresh_access_token(raise_on_failure=False)
        self.settings.write({'refresh_token': 'still-here'})
        with patch(PATH, return_value=(400, body)):
            self.settings._refresh_access_token(raise_on_failure=False)
        self.assertEqual(len(self.settings.message_ids) - before, 1)

    # ── F/G. dedicated, serialised token transaction ─────────────────────────

    def test_refresh_uses_a_dedicated_transaction(self):
        """The caller rolls back on any later GraphQL error; a refresh committed
        in the caller's cursor was lost together with the (already rotated, hence
        dead) old refresh token."""
        with patch(PATH, return_value=self._token_response(refresh_token='r9')):
            with patch.object(usa_settings, 'registry',
                              wraps=usa_settings.registry) as reg:
                self.assertTrue(self.settings._refresh_access_token())
        self.assertTrue(reg.called)
        # The other cursor wrote behind this recordset's back — cache invalidated.
        self.assertEqual(self.settings.refresh_token, 'r9')
        self.assertEqual(self.settings.access_token, 'new-access')

    def test_refresh_falls_back_to_the_caller_cursor(self):
        """A dedicated cursor is robustness, not a requirement."""
        with patch(PATH, return_value=self._token_response(refresh_token='r8')):
            with patch.object(usa_settings, 'registry',
                              side_effect=RuntimeError('no cursor')):
                self.assertTrue(self.settings._refresh_access_token())
        self.assertEqual(self.settings.refresh_token, 'r8')

    def test_refresh_skips_when_another_worker_already_refreshed(self):
        """Double-checked locking: the lock may be handed over by a worker that
        just refreshed, and a second POST would invalidate its fresh token."""
        with patch(PATH) as req:
            with patch.object(type(self.settings), '_is_token_valid',
                              return_value=True):
                self.assertTrue(self.settings._refresh_access_token())
        self.assertFalse(req.called)

    # ── Forced refresh (the "Refresh Token Now" button) ──────────────────────

    def test_force_refresh_bypasses_the_valid_token_shortcut(self):
        """Without `force` the double-check returns True *without* calling Upwork,
        so a diagnostic button would report a success that never happened."""
        self.settings.token_expiry = fields.Datetime.now() + timedelta(days=2)
        with patch(PATH, return_value=self._token_response(refresh_token='r5')) as req:
            self.assertTrue(
                self.settings._refresh_access_token(force=True))
        self.assertTrue(req.called)
        self.assertEqual(self.settings.refresh_token, 'r5')

    def test_force_refresh_still_takes_the_dedicated_transaction(self):
        """`force` skips the double-check only — the row lock and the committed
        cursor that fix defects F and G must stay on this path too."""
        self.settings.token_expiry = fields.Datetime.now() + timedelta(days=2)
        with patch(PATH, return_value=self._token_response(refresh_token='r6')):
            with patch.object(usa_settings, 'registry',
                              wraps=usa_settings.registry) as reg:
                self.assertTrue(self.settings._refresh_access_token(force=True))
        self.assertTrue(reg.called)

    def test_button_reports_rotation(self):
        """Whether Upwork rotates the refresh token is the fact the 1.23.0 fix
        hinges on; the button surfaces it without reading the server log."""
        with patch(PATH, return_value=self._token_response(refresh_token='r7')):
            action = self.settings.action_refresh_token_now()
        self.assertEqual(action['params']['type'], 'success')
        self.assertIn('rotated: yes', action['params']['message'])

        with patch(PATH, return_value=self._token_response()):
            action = self.settings.action_refresh_token_now()
        self.assertEqual(action['params']['type'], 'success')
        self.assertIn('rotated: no', action['params']['message'])

    def test_button_reports_failure_without_raising(self):
        """A Cloudflare HTML 400 must reach the user as a notification, and must
        not burn a live refresh token on the way."""
        with patch(PATH, return_value=(400, '<html>error 1020</html>')):
            action = self.settings.action_refresh_token_now()
        self.assertEqual(action['params']['type'], 'danger')
        self.assertTrue(action['params']['sticky'])
        self.assertEqual(self.settings.refresh_token, 'old-refresh')
        self.assertTrue(self.settings.token_last_error)

    def test_button_without_a_refresh_token_explains_itself(self):
        self.settings.write({'refresh_token': False})
        with patch(PATH) as req:
            with self.assertRaises(UserError):
                self.settings.action_refresh_token_now()
        self.assertFalse(req.called)

    # ── SOCKS5 without curl_cffi fails loudly ────────────────────────────────

    def test_socks5_without_curl_cffi_raises_instead_of_bypassing(self):
        """urllib cannot speak SOCKS5: going on would send the request past the
        proxy and collect a Cloudflare IP block that looks like a token problem."""
        with patch.object(usa_settings, '_curl_cffi', return_value=None):
            with self.assertRaises(UserError):
                usa_settings.upwork_request(
                    'https://www.upwork.com/api/v3/oauth2/token',
                    proxy='socks5h://user:pass@host:1080')

    # ── C. keep-alive cron ───────────────────────────────────────────────────

    def test_keepalive_refreshes_when_expiry_is_near(self):
        self.settings.token_expiry = fields.Datetime.now() + timedelta(hours=1)
        with patch(PATH, return_value=self._token_response(refresh_token='r2')) as req:
            self.env['usa.settings']._cron_refresh_token()
            self.assertTrue(req.called)
        self.assertEqual(self.settings.refresh_token, 'r2')

    def test_keepalive_skips_a_healthy_token(self):
        self.settings.token_expiry = fields.Datetime.now() + timedelta(days=2)
        with patch(PATH) as req:
            self.env['usa.settings']._cron_refresh_token()
        self.assertFalse(req.called)

    def test_keepalive_without_refresh_token_is_a_noop(self):
        self.settings.write({'refresh_token': False})
        with patch(PATH) as req:
            self.env['usa.settings']._cron_refresh_token()
        self.assertFalse(req.called)

    def test_keepalive_never_raises(self):
        self.settings.token_expiry = fields.Datetime.now() + timedelta(hours=1)
        with patch(PATH, return_value=(503, 'boom')):
            self.env['usa.settings']._cron_refresh_token()  # must not raise

    # ── D. 401 retry ─────────────────────────────────────────────────────────

    def test_graphql_401_refreshes_and_retries_once(self):
        """Upwork can revoke a token before `expires_in`; `_is_token_valid()` then
        never asks for a refresh, so the 401 has to drive it."""
        self.settings.token_expiry = fields.Datetime.now() + timedelta(hours=5)
        calls = []

        def fake(url, *args, **kwargs):
            calls.append(url)
            if 'oauth2/token' in url:
                return self._token_response(refresh_token='r3')
            if len([c for c in calls if 'graphql' in c]) == 1:
                return 401, 'unauthorized'
            return 200, json.dumps({'data': {'ok': True}})

        with patch(PATH, side_effect=fake):
            result = self.settings._graphql_query('{ ok }')
        self.assertEqual(result, {'data': {'ok': True}})
        self.assertEqual(len([c for c in calls if 'graphql' in c]), 2)
        self.assertEqual(self.settings.refresh_token, 'r3')

    def test_graphql_401_retries_only_once(self):
        self.settings.token_expiry = fields.Datetime.now() + timedelta(hours=5)

        def fake(url, *args, **kwargs):
            if 'oauth2/token' in url:
                return self._token_response()
            return 401, 'unauthorized'

        with patch(PATH, side_effect=fake):
            with self.assertRaises(UserError):
                self.settings._graphql_query('{ ok }')

# -*- coding: utf-8 -*-
"""Capture the Google Calendar OAuth ``?error`` that stock Odoo swallows.

The stock callback ``GoogleAuth.oauth2callback`` (google_account) just redirects
to ``state['f'] + "?error=..."`` on a failed/denied consent — nothing reads it,
so the user is bounced back to the calendar with no clue why nothing connected.
We store that reason on the user's ``google.calendar.credentials`` so the
friendly status badge in Preferences → Calendar can show it.

Safety (this route is shared by ALL Google services — calendar, gmail, drive):
  * we ONLY act when ``state['s'] == 'calendar'`` AND an ``error`` is present;
  * everything else (success ``code`` branch, every other service, the redirect
    response itself) is delegated verbatim to ``super()`` — we never duplicate
    the redirect/BadRequest logic;
  * the OAuth round-trip is same-browser/same-session, so ``request.env.user``
    is normally the real user — but a session can expire during a long consent,
    leaving the PUBLIC user. We guard with ``_is_public()`` and a defensive
    try/except so this auth=public route can never turn an error into a 500.
"""
import json
import logging

from odoo import http
from odoo.http import request
from odoo.addons.google_account.controllers.main import GoogleAuth

_logger = logging.getLogger(__name__)


class GoogleMeetGoogleAuth(GoogleAuth):

    @http.route()
    def oauth2callback(self, **kw):
        if kw.get('error'):
            try:
                state = json.loads(kw.get('state', '{}'))
            except ValueError:
                state = {}
            user = request.env.user
            if state.get('s') == 'calendar' and user and not user._is_public():
                account = user.sudo().google_calendar_account_id
                if account:
                    try:
                        account._record_calendar_error(
                            _human_oauth_error(kw.get('error')))
                    except Exception:  # bookkeeping must never break the redirect
                        _logger.exception(
                            "google_meet_integration: could not store OAuth "
                            "error for user id=%s", user.id)
        # Stock handles the actual redirect (success, error, or BadRequest).
        return super().oauth2callback(**kw)


def _human_oauth_error(error_code):
    """Map common Google OAuth error codes to a short, plain (escaped-by-default)
    explanation. Unknown codes are passed through as-is."""
    mapping = {
        'access_denied': "Access was denied on the Google consent screen "
                         "(you cancelled, or the app is not approved for your account).",
        'admin_policy_enforced': "Your Google Workspace admin blocked this app.",
        'org_internal': "This app is restricted to another Google organisation.",
        'redirect_uri_mismatch': "Redirect URI mismatch — the Odoo callback URL "
                                 "is not whitelisted in the Google project.",
    }
    base = mapping.get(error_code, "Google returned an error during consent.")
    return "%s [%s]" % (base, error_code)

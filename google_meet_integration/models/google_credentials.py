# -*- coding: utf-8 -*-
"""Surface the otherwise-invisible Google Calendar connection state.

Stock Odoo swallows the two things a user needs to self-diagnose a broken
calendar connection:
  * the OAuth consent ``?error`` (the callback just redirects with it in the
    query string and nobody reads it), and
  * the refresh-token failure reason (``_refresh_google_calendar_token`` wipes
    the token and raises a transient ``UserError`` that never reaches the form).

We persist both — plus the last successful sync time — on the per-account
``google.calendar.credentials`` record (the natural home, next to the tokens
they describe). ``res.users`` exposes them as related fields and a friendly
computed status; the controller (OAuth error) and the cron/on-load sync set
them. See ``res_users.py`` and ``controllers/google_account.py``.

Security: ``calendar_last_error`` holds a Google/attacker-controlled string, so
it is a plain ``Char`` and MUST only ever be rendered with default escaping
(never ``t-raw``/``Markup``).
"""
import logging

from odoo import fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Defensive cap — Google error/reason strings are short; avoid storing a giant
# value if an upstream message is ever unexpectedly large.
_MAX_ERROR_LEN = 512


class GoogleCredentials(models.Model):
    _inherit = 'google.calendar.credentials'

    calendar_last_sync_success = fields.Datetime(
        "Last Successful Sync", copy=False,
        help="Last time the calendar synced with Google without error.")
    calendar_last_sync_attempt = fields.Datetime(
        "Last Sync Attempt", copy=False,
        help="Last time a Google Calendar sync ran, whatever the outcome. "
             "Equals 'Last Successful Sync' on success; on failure it is later "
             "than the last success, so a stale/failing connection is obvious "
             "even when the error text is terse.")
    calendar_last_error = fields.Char(
        "Last Sync/Connection Error", copy=False,
        help="Human-readable reason of the last failed connection or sync "
             "(OAuth error code, token-refresh or sync failure). Cleared on "
             "the next successful sync.")
    calendar_last_error_date = fields.Datetime("Last Error On", copy=False)
    calendar_consecutive_failures = fields.Integer(
        "Consecutive Sync Failures", copy=False, default=0,
        help="How many connection/sync failures happened in a row since the "
             "last success. Reset to 0 on any successful sync or reconnect.")

    def _record_calendar_error(self, reason):
        """Persist a failure reason and bump the failure streak (sudo-written;
        callable from the public OAuth callback, the token-refresh path and the
        sync funnel)."""
        for rec in self:
            rec.sudo().write({
                'calendar_last_error': (reason or '')[:_MAX_ERROR_LEN],
                'calendar_last_error_date': fields.Datetime.now(),
                'calendar_consecutive_failures': rec.calendar_consecutive_failures + 1,
            })

    def _clear_calendar_error(self):
        for rec in self:
            if (rec.calendar_last_error or rec.calendar_last_error_date
                    or rec.calendar_consecutive_failures):
                rec.sudo().write({
                    'calendar_last_error': False,
                    'calendar_last_error_date': False,
                    'calendar_consecutive_failures': 0,
                })

    def _set_auth_tokens(self, access_token, refresh_token, ttl):
        res = super()._set_auth_tokens(access_token, refresh_token, ttl)
        # A real (re)connect just wrote a refresh token → drop any stale error
        # immediately, before the first sync even runs.
        if refresh_token:
            self._clear_calendar_error()
        return res

    def _refresh_google_calendar_token(self):
        try:
            return super()._refresh_google_calendar_token()
        except UserError as e:
            # Stock has already rolled back and (on 400/401) wiped the tokens
            # before raising, so a write made *before* super() would be lost.
            # Persist the reason in its own committed transaction, then re-raise
            # so the caller still sees the original error.
            try:
                self._record_calendar_error(str(e))
                self.env.cr.commit()
            except Exception:  # never let bookkeeping mask the real error
                _logger.exception(
                    "google_meet_integration: failed to persist token-refresh "
                    "error for credentials id=%s", self.ids)
            raise

# -*- coding: utf-8 -*-
import logging

from odoo import _, fields, models

_logger = logging.getLogger(__name__)

# How far the on-demand "Sync now" button reaches when it forces a FULL Google
# Calendar pull. Asymmetric on purpose: a short look-back to recover recently
# added/edited past meetings, a longer look-ahead for upcoming ones. This
# replaces the stock symmetric ±`google_calendar.sync.range_days` (default 365)
# window. Both bounds are overridable via ir.config_parameter, no code change.
SYNC_NOW_PAST_DAYS_PARAM = 'google_meet_integration.sync_now.past_days'
SYNC_NOW_FUTURE_DAYS_PARAM = 'google_meet_integration.sync_now.future_days'
SYNC_NOW_DEFAULT_PAST_DAYS = 7
SYNC_NOW_DEFAULT_FUTURE_DAYS = 30


def _build_narrow_window_service(google_service, past_days, future_days):
    """Build a GoogleCalendarService whose FULL sync is restricted to
    ``[now - past_days, now + future_days]`` instead of the stock symmetric
    ±``google_calendar.sync.range_days`` (default 365) window.

    Defined lazily (NOT at import time) so the dependency on the private
    ``google_calendar`` util can only ever break this one button at runtime,
    never abort ``res.users`` at server boot — same boot-safety contract as
    ``action_sync_google_calendar_now`` below.

    Only the full-sync path is reshaped; incremental syncs (with a sync_token)
    and single-event fetches are delegated to the parent verbatim — the window
    has no meaning there. The full-sync branch faithfully mirrors
    ``GoogleCalendarService.get_events`` (Odoo 17 ``google_calendar`` util) so a
    maintainer can diff the two; only the timeMin/timeMax bounds differ.
    """
    import requests
    from odoo.addons.google_account.models.google_service import TIMEOUT
    from odoo.addons.google_calendar.utils.google_calendar import (
        GoogleCalendarService, InvalidSyncToken,
    )
    from odoo.addons.google_calendar.utils.google_event import GoogleEvent

    class _NarrowWindowGoogleCalendarService(GoogleCalendarService):
        def get_events(self, sync_token=None, token=None, event_id=None, timeout=TIMEOUT):
            # Reshape only the full pull; everything else is the parent's job.
            if sync_token or event_id:
                return super().get_events(
                    sync_token=sync_token, token=token,
                    event_id=event_id, timeout=timeout)
            if not token:
                raise AttributeError("An authentication token is required")
            url = "/calendar/v3/calendars/primary/events"
            headers = {'Content-type': 'application/json'}
            now = fields.Datetime.now()
            params = {
                'access_token': token,
                # Z = UTC (RFC3339), as in the stock util.
                'timeMin': fields.Datetime.subtract(now, days=past_days).isoformat() + 'Z',
                'timeMax': fields.Datetime.add(now, days=future_days).isoformat() + 'Z',
            }
            _logger.info(
                "google_meet_integration: forced full Google Calendar sync "
                "restricted to [-%sd, +%sd]", past_days, future_days)
            try:
                status, data, _t = self.google_service._do_request(
                    url, params, headers, method='GET', timeout=timeout)
            except requests.HTTPError as e:
                if e.response.status_code == 410 and 'fullSyncRequired' in str(e.response.content):
                    raise InvalidSyncToken("Invalid sync token. Full sync required")
                raise
            events = data.get('items', [])
            next_page_token = data.get('nextPageToken')
            while next_page_token:
                params = {'access_token': token, 'pageToken': next_page_token}
                status, data, _t = self.google_service._do_request(
                    url, params, headers, method='GET', timeout=timeout)
                next_page_token = data.get('nextPageToken')
                events += data.get('items', [])
            next_sync_token = data.get('nextSyncToken')
            default_reminders = data.get('defaultReminders')
            return GoogleEvent(events), next_sync_token, default_reminders

    return _NarrowWindowGoogleCalendarService(google_service)


class ResUsers(models.Model):
    _inherit = 'res.users'

    def _sync_now_window_days(self):
        """Return the (past_days, future_days) reach of the manual "Sync now"
        forced full pull, read from ir.config_parameter with sane defaults.
        Negative values are clamped to 0 (today)."""
        ICP = self.env['ir.config_parameter'].sudo()
        past = int(ICP.get_param(SYNC_NOW_PAST_DAYS_PARAM, SYNC_NOW_DEFAULT_PAST_DAYS))
        future = int(ICP.get_param(SYNC_NOW_FUTURE_DAYS_PARAM, SYNC_NOW_DEFAULT_FUTURE_DAYS))
        return max(past, 0), max(future, 0)

    def action_sync_google_calendar_now(self):
        """On-demand FULL pull/push with Google Calendar for the CURRENT user,
        restricted to the recent-past → near-future window
        (``[-past_days, +future_days]``, default -7d/+30d).

        Backend twin of the in-calendar "Sync now" button. Unlike the stock
        per-calendar-load sync (which, once a sync_token exists, only fetches
        *incremental changes* and silently never re-imports meetings that fell
        outside the original full-sync window), this action FORCES a full sync
        over a focused window: it clears the stored sync_token so the next pull
        takes the full-sync branch, then runs the per-user sync with a service
        whose window is our narrow asymmetric range. Core writes a fresh
        sync_token back on success, so normal incremental auto-sync resumes.

        This is the lever that recovers meetings missing from a user's Odoo
        calendar (e.g. created/edited while outside the stock ±1y window).
        Always acts on ``env.user`` — Google sync is per-user, bound to that
        user's own OAuth token. Returns a client notification.
        """
        user = self.env.user
        if not user.is_google_calendar_synced():
            return self._google_meet_sync_notification(
                _("Google Calendar is not connected. Connect it from your "
                  "Preferences, then try again."),
                'warning')
        try:
            past_days, future_days = self._sync_now_window_days()
            # Force a FULL sync: clear the sync_token so `_sync_request` takes
            # the full-sync branch and our narrow window actually applies. An
            # already-connected user otherwise has a token and Google returns
            # only incremental changes, ignoring any window.
            account = user.google_calendar_account_id
            if account:
                account.sudo().calendar_sync_token = False
            service = _build_narrow_window_service(
                self.env['google.service'], past_days, future_days)
            # with_user(user).sudo(): mirror res.users._sync_all_google_calendar
            # so the sync runs as the owner with their token, under sudo.
            user.with_user(user).sudo()._sync_google_calendar(service)
        except Exception:
            _logger.exception(
                "google_meet_integration: manual Google Calendar sync failed "
                "for user id=%s", user.id)
            return self._google_meet_sync_notification(
                _("Could not sync with Google Calendar. Please try again, or "
                  "reconnect your account from Preferences."),
                'danger')
        return self._google_meet_sync_notification(
            _("Calendar synced with Google."), 'success')

    def _google_meet_sync_notification(self, message, ntype):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Google Calendar'),
                'message': message,
                'type': ntype,
                'sticky': False,
            },
        }

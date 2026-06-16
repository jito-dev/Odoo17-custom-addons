# -*- coding: utf-8 -*-
import logging

from odoo import _, models
from odoo.addons.google_calendar.utils.google_calendar import (
    GoogleCalendarService,
)

_logger = logging.getLogger(__name__)


class ResUsers(models.Model):
    _inherit = 'res.users'

    def action_sync_google_calendar_now(self):
        """On-demand pull/push with Google Calendar for the CURRENT user.

        Backend twin of the in-calendar "Sync now" button: runs the same
        per-user `_sync_google_calendar` the calendar view triggers on load, so
        a recruiter (or support/admin) can force a refresh without reopening the
        Calendar. Always acts on `env.user` — Google sync is per-user and bound
        to that user's own OAuth token. Returns a client notification.
        """
        user = self.env.user
        if not user.is_google_calendar_synced():
            return self._google_meet_sync_notification(
                _("Google Calendar is not connected. Connect it from your "
                  "Preferences, then try again."),
                'warning')
        try:
            service = GoogleCalendarService(self.env['google.service'])
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

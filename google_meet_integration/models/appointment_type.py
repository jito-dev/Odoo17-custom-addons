# -*- coding: utf-8 -*-
import logging

from markupsafe import Markup

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class AppointmentType(models.Model):
    _inherit = 'appointment.type'

    # Make Google Meet the default (and, with the hidden selector in
    # views/appointment_type_views.xml, effectively the only) videoconference
    # source for every Appointment Type — for an organisation that does not use
    # Odoo Discuss video. We redefine ONLY the default of the native Selection;
    # the values themselves (incl. the 'google_meet' option added by
    # appointment_google_calendar) are inherited untouched. 'google_meet' is a
    # valid value here because this module depends on appointment_google_calendar.
    event_videocall_source = fields.Selection(default='google_meet')

    # Warning shown on the form when one or more assigned staff have NOT
    # connected their Google Calendar. With the native 'google_meet' source the
    # Meet link is minted only when the event syncs to the organiser's Google
    # calendar — so an unconnected staff member's bookings can end up WITHOUT a
    # Meet link. This is the clean, native-only successor of the old
    # ``users_wo_google_meet_msg`` field (which was tied to the removed REST
    # ``google_meet_rest`` path): it has NO dependency on google.meet.service,
    # the OAuth-scope monkeypatch or any fallback user, and uses only the public
    # ``res.users.is_google_calendar_synced()``.
    google_meet_unsynced_staff_warning = fields.Html(
        string="Google Meet Connection Warning",
        compute='_compute_google_meet_unsynced_staff_warning',
        sanitize=False,
    )

    @api.depends('staff_user_ids', 'event_videocall_source')
    def _compute_google_meet_unsynced_staff_warning(self):
        for appointment_type in self:
            warning = False
            if appointment_type.event_videocall_source == 'google_meet':
                unsynced = appointment_type.staff_user_ids.filtered(
                    lambda user: not self._user_google_calendar_synced(user)
                )
                if unsynced:
                    names = Markup(', ').join(
                        Markup('<b>%s</b>') % user.name for user in unsynced
                    )
                    body = _(
                        "Not connected to Google Calendar: %(names)s. Their "
                        "bookings may be created without a Google Meet link "
                        "until they connect it from Preferences → Calendar.",
                        names=names,
                    )
                    warning = Markup(
                        '<div class="alert alert-warning mb-0" role="alert">'
                        '%s</div>'
                    ) % body
            appointment_type.google_meet_unsynced_staff_warning = warning

    @staticmethod
    def _user_google_calendar_synced(user):
        """Best-effort connection check that never raises into the compute.

        sudo(): reading another user's Google token requires elevated rights.
        Any access/refresh error is treated as 'not synced' (the safe default
        that surfaces the warning rather than hiding a real gap).
        """
        try:
            return bool(user.sudo().is_google_calendar_synced())
        except Exception:
            _logger.debug(
                "google_meet_integration: could not read Google sync status "
                "for user id=%s; treating as not connected.", user.id,
                exc_info=True,
            )
            return False

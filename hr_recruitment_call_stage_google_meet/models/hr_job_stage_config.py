# -*- coding: utf-8 -*-
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class HrJobStageConfig(models.Model):
    _inherit = 'hr.job.stage.config'

    # When a stage is configured as a Call Stage, its booking appointment type
    # must produce a Google Meet link so every booked call event carries a
    # videocall_location with zero recruiter configuration. We force that
    # type's ``event_videocall_source`` to 'google_meet' — the NATIVE option
    # added by ``appointment_google_calendar``. That makes Odoo's own Google
    # Calendar sync attach a Meet conference (``conferenceData.createRequest``)
    # to the event, exactly like the link Google creates when a recruiter
    # manually adds a calendar event. The Meet URL is pulled back into
    # ``calendar.event.videocall_location`` on the next sync.
    #
    # Why native and not the REST mint (google_meet_integration's
    # 'google_meet_rest'): the REST path needs the extra Meet API OAuth scope
    # (``meetings.space.created``), which connected accounts do not have unless
    # they re-consent — so it 403s and bookings get no link. The native path
    # needs only the Calendar scope every synced user already granted, and it
    # is the mechanism that actually worked in production.

    def _apply_call_stage_google_meet_source(self):
        """Force 'google_meet' as the videoconference source of each Call
        Stage's booking appointment type, and log a warning when no staff user
        is synced with Google Calendar (so no Meet link can be created)."""
        for config in self:
            appt_type = config.booking_appointment_type_id
            if not (config.is_call_stage and appt_type):
                continue
            if appt_type.event_videocall_source != 'google_meet':
                # sudo(): a recruiter editing the stage config may lack write
                # access to appointment.type, but the intent is system policy.
                appt_type.sudo().event_videocall_source = 'google_meet'
            # Reliability check — the native flow only creates a Meet link for
            # staff users whose Google Calendar is connected. If none are
            # synced, booked calls will have no Meet link.
            has_sync = any(
                user.is_google_calendar_synced()
                for user in appt_type.staff_user_ids
            )
            if not has_sync:
                _logger.warning(
                    "Call Stage config id=%s: appointment type '%s' is set to "
                    "Google Meet, but no staff user has a connected Google "
                    "Calendar — booked calls will have no Meet link. Connect a "
                    "staff user's Google Calendar from Preferences.",
                    config.id, appt_type.name,
                )

    @api.model_create_multi
    def create(self, vals_list):
        configs = super().create(vals_list)
        configs._apply_call_stage_google_meet_source()
        return configs

    def write(self, vals):
        res = super().write(vals)
        # Re-apply only when the toggle or the booking type could have changed.
        if {'is_call_stage', 'booking_appointment_type_id'} & set(vals):
            self._apply_call_stage_google_meet_source()
        return res

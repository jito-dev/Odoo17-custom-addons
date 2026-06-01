# -*- coding: utf-8 -*-
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class HrJobStageConfig(models.Model):
    _inherit = 'hr.job.stage.config'

    # When a stage is configured as a Call Stage, its booking appointment type
    # must mint a Google Meet link so every booked call event carries a
    # videocall_location with zero recruiter configuration. We force that
    # type's ``event_videocall_source`` to 'google_meet' (the option added by
    # google_meet_integration), which makes that module REST-mint the Meet URL
    # up-front at booking time and write it straight onto the calendar event.

    def _apply_call_stage_google_meet_source(self):
        """Force 'google_meet' as the videoconference source of each Call
        Stage's booking appointment type, and log a warning when no Google
        connection (staff user token or admin fallback) can satisfy the mint."""
        AppointmentType = self.env['appointment.type']
        fallback_user = self.env['google.meet.service']._get_fallback_user()
        for config in self:
            appt_type = config.booking_appointment_type_id
            if not (config.is_call_stage and appt_type):
                continue
            if appt_type.event_videocall_source != 'google_meet':
                # sudo(): a recruiter editing the stage config may lack write
                # access to appointment.type, but the intent is system policy.
                appt_type.sudo().event_videocall_source = 'google_meet'
            # Reliability check — a 'google_meet' source still needs *some*
            # connected Google account to mint the space.
            has_connection = fallback_user or any(
                AppointmentType._user_has_google_token(user)
                for user in appt_type.staff_user_ids
            )
            if not has_connection:
                _logger.warning(
                    "Call Stage config id=%s: appointment type '%s' is set to "
                    "Google Meet, but no staff user has a connected Google "
                    "Calendar and no fallback Meet user is configured — booked "
                    "calls will have no Meet link. Configure a fallback Meet "
                    "user in Settings or connect a staff user's Google account.",
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

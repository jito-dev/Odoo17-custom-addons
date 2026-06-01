# -*- coding: utf-8 -*-
from odoo import api, models


class CalendarEvent(models.Model):
    _inherit = 'calendar.event'

    # Bridge hooks that translate calendar-event lifecycle changes into the
    # call_stage cockpit signals (booked / rescheduled / cancelled). All
    # state lives on hr.applicant; this model only detects the transitions.
    # super() chains through hr_recruitment_call_stage's own create/write
    # (event rename + auto-advance + reschedule note) — we run after it.
    #
    # The Google Meet link itself is minted UP-FRONT (REST) by
    # google_meet_integration when the appointment type's videocall source is
    # 'google_meet_rest' — which the bridge guarantees for Call Stage booking types
    # (see hr_job_stage_config.py). So a booked call event already carries its
    # videocall_location by the time these hooks run; this model never mints.

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for event in records:
            if event.applicant_id and event.appointment_invite_id:
                event.applicant_id._call_meet_on_booking(event)
        return records

    def write(self, vals):
        archiving = vals.get('active') is False
        start_changing = 'start' in vals
        # Snapshot the previous start so a no-op write (start set to the same
        # value) does not register as a reschedule.
        old_starts = {}
        if start_changing:
            old_starts = {
                event.id: event.start
                for event in self
                if event.applicant_id and event.active
            }

        res = super().write(vals)

        if archiving:
            for event in self:
                if event.applicant_id and event.appointment_invite_id:
                    event.applicant_id._call_meet_on_cancel(event)
        elif start_changing:
            for event in self:
                if not (event.applicant_id and event.appointment_invite_id):
                    continue
                old_start = old_starts.get(event.id)
                if old_start and old_start != event.start:
                    event.applicant_id._call_meet_on_reschedule(event)

        return res

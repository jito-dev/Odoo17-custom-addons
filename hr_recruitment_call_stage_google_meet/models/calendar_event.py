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
    # The Google Meet link itself comes from the NATIVE Google Calendar sync:
    # the bridge forces the Call Stage booking type's videocall source to
    # 'google_meet' (see hr_job_stage_config.py), so Odoo attaches a Meet
    # conference on sync and writes the URL onto videocall_location. That sync
    # is asynchronous, so the link may arrive shortly after these hooks run —
    # the cockpit reads it live off the event. This model never mints.

    def _write_from_google(self, gevent, vals):
        """Mark writes that arrive FROM Google, so a cancellation knows its source.

        An event deleted in Google Calendar comes back as ``active: False``
        through the stock sync and is indistinguishable, at the point our
        ``write`` override sees it, from a recruiter archiving the record by
        hand. The distinction matters only for the wording of the chatter note
        — but that note used to name whichever colleague's calendar happened to
        carry the event, which is the opposite of informative.

        The flag rides the context rather than a field: it is true for the
        duration of this write and of nothing else.
        """
        return super(
            CalendarEvent,
            self.with_context(call_stage_cancel_from_google=True),
        )._write_from_google(gevent, vals)

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

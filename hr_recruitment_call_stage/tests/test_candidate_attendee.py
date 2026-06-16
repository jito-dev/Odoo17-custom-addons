# -*- coding: utf-8 -*-
"""v17.0.20.0.0 — the candidate is always an attendee of their booked call.

Regression cover for the recruiter-on-behalf booking gap: when a recruiter
books from the Call Stage (the booker is the recruiter, not the candidate),
the stock appointment flow seeds attendees from the booker only, so the
candidate was silently left off ``partner_ids`` — no invite, no Google
Calendar sync. ``_call_stage_ensure_candidate_attendee`` closes that gap.

The pre-existing ``test_interviewers`` suite never caught this because its
``_create_event`` helper hand-seeds ``applicant.partner_id`` into
``partner_ids`` (mimicking the public-portal path where the candidate IS the
booker). These tests deliberately omit the candidate from the create vals.
"""
from datetime import datetime, timedelta

from odoo.tests import tagged

from .common import CallStageTestCommon


@tagged('post_install', '-at_install')
class TestCandidateAttendee(CallStageTestCommon):
    def _enable(self, job, appt_type):
        cfg = self._get_config(job, self.stage_call)
        cfg.write({
            'is_call_stage': True,
            'booking_appointment_type_id': appt_type.id,
        })
        return cfg

    def _recruiter_books(self, applicant, appt_type, invite, attendees):
        """Simulate a recruiter-on-behalf booking: attendees carry whoever
        the stock flow would seed (recruiter/booker) but NOT the candidate."""
        start = datetime.now() + timedelta(days=1)
        return self.CalendarEvent.create({
            'name': 'STOCK PLACEHOLDER — overridden',
            'start': start,
            'stop': start + timedelta(minutes=30),
            'appointment_type_id': appt_type.id,
            'appointment_invite_id': invite.id,
            'partner_ids': [(6, 0, attendees.ids)],
        })

    def test_candidate_added_when_recruiter_books(self):
        self._enable(self.job_designer, self.appt_hr_call)
        recruiter = self.env['res.users'].create({
            'name': 'Rita Recruiter CS',
            'login': 'rita_recruiter_cs@example.com',
            'email': 'rita_recruiter_cs@example.com',
        })
        applicant = self._make_applicant('Cand Carl CS', self.job_designer)
        applicant.stage_id = self.stage_call.id
        # Give the candidate a real contact with an email (as a portal booking
        # or a manually-created contact would).
        applicant.partner_id = self.env['res.partner'].create({
            'name': 'Cand Carl CS',
            'email': 'cand_carl_cs@example.com',
        })
        invite = applicant._get_or_create_booking_invite(self.appt_hr_call)

        event = self._recruiter_books(
            applicant, self.appt_hr_call, invite, recruiter.partner_id)

        self.assertIn(applicant.partner_id, event.partner_ids,
            "the candidate must be added as an attendee even when the "
            "recruiter is the booker")
        self.assertIn(recruiter.partner_id, event.partner_ids,
            "the recruiter/booker stays an attendee")

    def test_candidate_fallback_from_email_when_no_partner(self):
        self._enable(self.job_designer, self.appt_hr_call)
        applicant = self._make_applicant('Cand Dora CS', self.job_designer)
        applicant.stage_id = self.stage_call.id
        applicant.partner_id = False
        applicant.email_from = 'cand_dora_cs@example.com'
        invite = applicant._get_or_create_booking_invite(self.appt_hr_call)

        event = self._recruiter_books(
            applicant, self.appt_hr_call, invite, self.env['res.partner'])

        emails = event.partner_ids.mapped('email')
        self.assertIn('cand_dora_cs@example.com', emails,
            "with no candidate partner, the application email must still be "
            "resolved to an attendee so the invite reaches the candidate")

    def test_attendee_change_rearms_google_sync(self):
        """v17.0.21.0.0 — adding an attendee after the booking must re-arm
        ``need_sync`` so the change is pushed to Google.

        ``partner_ids`` is NOT in ``_get_google_synced_fields()`` (only
        ``attendee_ids`` is), so a bare ``partner_ids`` write leaves
        ``need_sync`` untouched. Because google_calendar's ``_google_insert``
        already ran (and cleared the flag) during ``create``, any later
        attendee added via ``partner_ids`` would never reach Google — the
        recruiter-on-behalf / interviewer no-invite bug. The fix forces
        ``need_sync=True`` on those writes; this test asserts the flag flips
        back so Odoo emits a ``_google_patch``.
        """
        self._enable(self.job_designer, self.appt_hr_call)
        applicant = self._make_applicant('Cand Sync CS', self.job_designer)
        applicant.stage_id = self.stage_call.id
        applicant.partner_id = self.env['res.partner'].create({
            'name': 'Cand Sync CS',
            'email': 'cand_sync_cs@example.com',
        })
        invite = applicant._get_or_create_booking_invite(self.appt_hr_call)
        event = self._recruiter_books(
            applicant, self.appt_hr_call, invite, applicant.partner_id)

        # ``need_sync`` only exists when the enterprise ``google_calendar``
        # module is installed (not a hard dependency here). The re-arm is a
        # no-op without it, so the assertion is scoped to that case; the
        # attendee-presence assertion below always holds.
        has_google = 'need_sync' in event._fields
        if has_google:
            # Simulate "already pushed to Google": clear the pending-sync flag
            # the same way a successful insert would. A bare need_sync write
            # does not re-arm itself, so the flag stays down.
            event.with_context(dont_notify=True).write({'need_sync': False})
            self.assertFalse(event.need_sync,
                "precondition: the event is considered synced (no pending push)")

        # Recruiter adds an interviewer after the booking — this reconciles the
        # future event's attendees via the fixed code path.
        interviewer = self.env['res.users'].create({
            'name': 'Ivan Interviewer CS',
            'login': 'ivan_interviewer_cs@example.com',
            'email': 'ivan_interviewer_cs@example.com',
        })
        applicant.call_interviewer_user_ids = [(4, interviewer.id)]

        self.assertIn(interviewer.partner_id, event.partner_ids,
            "the interviewer is added as an attendee")
        if has_google:
            self.assertTrue(event.need_sync,
                "adding an attendee must re-arm need_sync so the new guest is "
                "pushed to Google and actually receives an invite")

    def test_no_double_add_for_public_booking(self):
        # Candidate IS the booker (public portal) — already an attendee. The
        # guarantee must be a no-op, not a duplicate.
        self._enable(self.job_designer, self.appt_hr_call)
        applicant = self._make_applicant('Cand Ella CS', self.job_designer)
        applicant.stage_id = self.stage_call.id
        applicant.partner_id = self.env['res.partner'].create({
            'name': 'Cand Ella CS',
            'email': 'cand_ella_cs@example.com',
        })
        invite = applicant._get_or_create_booking_invite(self.appt_hr_call)

        event = self._recruiter_books(
            applicant, self.appt_hr_call, invite, applicant.partner_id)

        self.assertEqual(
            event.partner_ids.filtered(lambda p: p == applicant.partner_id),
            applicant.partner_id,
            "the candidate appears exactly once, not duplicated")

    # v17.0.24.11.0 — the candidate (+ seeded interviewers) are injected into
    # the create vals so the SYNCHRONOUS google_calendar `_google_insert` (run
    # for a Google-synced recruiter booking on-behalf) already carries them as
    # guests, instead of relying on the post-create `_google_patch` (timeout=3)
    # that could drop the candidate off the Google event entirely.
    def test_collect_booking_attendee_ids(self):
        self._enable(self.job_designer, self.appt_hr_call)
        applicant = self._make_applicant('Cand Fred CS', self.job_designer)
        applicant.stage_id = self.stage_call.id
        applicant.partner_id = self.env['res.partner'].create({
            'name': 'Cand Fred CS', 'email': 'cand_fred_cs@example.com'})
        interviewer = self.env['res.users'].create({
            'name': 'Iryna Interviewer CS',
            'login': 'iryna_interviewer_cs@example.com',
            'email': 'iryna_interviewer_cs@example.com'})
        applicant.call_interviewer_user_ids = [(4, interviewer.id)]

        ids = self.CalendarEvent._call_stage_collect_booking_attendee_ids(
            applicant)

        self.assertIn(applicant.partner_id.id, ids,
            "candidate must be injected so the first Google push invites them")
        self.assertIn(interviewer.partner_id.id, ids,
            "seeded interviewers are injected too")
        self.assertEqual(len(ids), len(set(ids)), "no duplicate guest ids")

    def test_collect_booking_attendee_ids_email_fallback(self):
        self._enable(self.job_designer, self.appt_hr_call)
        applicant = self._make_applicant('Cand Gwen CS', self.job_designer)
        applicant.stage_id = self.stage_call.id
        applicant.partner_id = False
        applicant.email_from = 'cand_gwen_cs@example.com'

        ids = self.CalendarEvent._call_stage_collect_booking_attendee_ids(
            applicant)
        partners = self.env['res.partner'].browse(ids)

        self.assertIn('cand_gwen_cs@example.com', partners.mapped('email'),
            "with no candidate partner, the application email is resolved so "
            "the candidate is still a guest on the very first Google push")

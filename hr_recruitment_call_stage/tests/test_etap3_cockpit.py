# -*- coding: utf-8 -*-
"""Etap 3 (v17.0.3.0.0) — recruiter cockpit on hr.applicant."""
from datetime import datetime, timedelta

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import CallStageTestCommon


@tagged('post_install', '-at_install')
class TestEtap3Cockpit(CallStageTestCommon):
    def _enable(self, job, appt_type):
        cfg = self._get_config(job, self.stage_call)
        cfg.write({
            'is_call_stage': True,
            'booking_appointment_type_id': appt_type.id,
        })
        return cfg

    # ---- 3.1: status transitions through the cockpit lifecycle -------
    def test_call_status_no_link_then_link_ready(self):
        self._enable(self.job_designer, self.appt_hr_call)
        applicant = self._make_applicant(
            'Anna E3 CS', self.job_designer, self.stage_call)
        self.assertEqual(applicant.call_status, 'no_link')
        applicant.action_generate_booking_link()
        applicant.invalidate_recordset(['call_status', 'booking_url'])
        self.assertEqual(applicant.call_status, 'link_ready')
        self.assertTrue(applicant.booking_url)

    def test_call_status_advances_to_booked_on_event_create(self):
        self._enable(self.job_designer, self.appt_hr_call)
        applicant = self._make_applicant(
            'Boris E3 CS', self.job_designer, self.stage_call)
        invite = applicant._get_or_create_booking_invite(self.appt_hr_call)
        start = datetime.now() + timedelta(days=1)
        self.CalendarEvent.create({
            'name': 'X',
            'start': start,
            'stop': start + timedelta(minutes=30),
            'appointment_type_id': self.appt_hr_call.id,
            'appointment_invite_id': invite.id,
            'partner_ids': [(6, 0, applicant.partner_id.ids)]
                           if applicant.partner_id else False,
        })
        # Stage auto-advances to Call Booked; booking_url still resolved
        # via fallback search → status flips to 'booked'.
        applicant.invalidate_recordset(['call_status', 'stage_id'])
        self.assertEqual(applicant.call_status, 'booked')

    def test_call_status_booked_with_multiple_call_stages(self):
        # Regression: a job with TWO Call Stages must still read 'booked' after
        # a booking + auto-advance. The status now resolves the booked event
        # across ALL the job's call types, so it no longer depends on which
        # config the (arbitrary) current-stage fallback happens to pick.
        self._enable(self.job_designer, self.appt_hr_call)
        stage_call_2 = self.Stage.create({
            'name': 'Second call CS', 'sequence': 35,
            'job_ids': [(6, 0, [self.job_designer.id])],
        })
        cfg2 = self._get_config(self.job_designer, stage_call_2)
        cfg2.write({'is_call_stage': True,
                    'booking_appointment_type_id': self.appt_tech_call.id})
        applicant = self._make_applicant(
            'Carl E3 CS', self.job_designer, self.stage_call)
        invite = applicant._get_or_create_booking_invite(self.appt_hr_call)
        start = datetime.now() + timedelta(days=1)
        self.CalendarEvent.create({
            'name': 'Y',
            'start': start,
            'stop': start + timedelta(minutes=30),
            'appointment_type_id': self.appt_hr_call.id,
            'appointment_invite_id': invite.id,
            'partner_ids': [(6, 0, applicant.partner_id.ids)]
                           if applicant.partner_id else False,
        })
        applicant.invalidate_recordset(['call_status', 'stage_id'])
        self.assertEqual(applicant.call_status, 'booked',
            "a booked call must read 'booked' even with multiple Call Stages")

    def test_booked_event_scoping_by_appt_type(self):
        # v17.0.24.12.0 — a booking on ONE call type must be visible job-wide
        # but invisible when the lookup is scoped to a DIFFERENT call type.
        self._enable(self.job_designer, self.appt_hr_call)
        applicant = self._make_applicant(
            'Greta E3 CS', self.job_designer, self.stage_call)
        invite = applicant._get_or_create_booking_invite(self.appt_hr_call)
        start = datetime.now() + timedelta(days=1)
        self.CalendarEvent.create({
            'name': 'Z', 'start': start, 'stop': start + timedelta(minutes=30),
            'appointment_type_id': self.appt_hr_call.id,
            'appointment_invite_id': invite.id,
            'partner_ids': [(6, 0, applicant.partner_id.ids)]
                           if applicant.partner_id else False,
        })
        self.assertTrue(applicant._get_booked_call_event(),
            "job-wide lookup sees the booking")
        self.assertTrue(applicant._get_booked_call_event(
            appt_types=self.appt_hr_call), "scoped to its own type: booked")
        self.assertFalse(applicant._get_booked_call_event(
            appt_types=self.appt_tech_call),
            "scoped to a DIFFERENT call type: not booked")

    def test_booked_does_not_stick_when_moved_to_other_call_stage(self):
        # The reported bug: book Call Stage A, then move the candidate to a
        # different Call Stage B → the chip must reflect B's own (unbooked)
        # status, not the stale 'booked' from A.
        self._enable(self.job_designer, self.appt_hr_call)
        stage_call_2 = self.Stage.create({
            'name': 'Second call CS3', 'sequence': 36,
            'job_ids': [(6, 0, [self.job_designer.id])]})
        cfg2 = self._get_config(self.job_designer, stage_call_2)
        cfg2.write({'is_call_stage': True,
                    'booking_appointment_type_id': self.appt_tech_call.id})
        applicant = self._make_applicant(
            'Hugo E3 CS', self.job_designer, self.stage_call)
        invite = applicant._get_or_create_booking_invite(self.appt_hr_call)
        start = datetime.now() + timedelta(days=1)
        self.CalendarEvent.create({
            'name': 'Z', 'start': start, 'stop': start + timedelta(minutes=30),
            'appointment_type_id': self.appt_hr_call.id,
            'appointment_invite_id': invite.id,
            'partner_ids': [(6, 0, applicant.partner_id.ids)]
                           if applicant.partner_id else False,
        })
        applicant.invalidate_recordset(['call_status', 'stage_id'])
        self.assertEqual(applicant.call_status, 'booked',
            "booked while on the auto-advanced (non-call) Call Booked stage")
        # Move to the SECOND call stage: its own type is not booked.
        applicant.stage_id = stage_call_2.id
        applicant.invalidate_recordset(['call_status'])
        self.assertNotEqual(applicant.call_status, 'booked',
            "a booking on the earlier call stage must not mask the new call "
            "stage's own status")

    def test_sent_marker_is_per_invite(self):
        # v17.0.24.12.0 — `sent` is recorded per-invite, so a send on one Call
        # Stage's invite does not mark a sibling invite as sent.
        self._enable(self.job_designer, self.appt_hr_call)
        applicant = self._make_applicant(
            'Iris E3 CS', self.job_designer, self.stage_call)
        invite_a = applicant._get_or_create_booking_invite(self.appt_hr_call)
        invite_b = applicant._get_or_create_booking_invite(self.appt_tech_call)

        self.assertFalse(applicant._has_call_invite_sent_marker(invite_a))
        applicant._post_call_invite_sent_marker(invite_a)
        self.assertTrue(applicant._has_call_invite_sent_marker(invite_a))
        self.assertFalse(applicant._has_call_invite_sent_marker(invite_b),
            "a send for one invite must not mark a sibling invite as sent")

    def test_legacy_bare_sent_marker_still_counts(self):
        self._enable(self.job_designer, self.appt_hr_call)
        applicant = self._make_applicant(
            'Jack E3 CS', self.job_designer, self.stage_call)
        invite = applicant._get_or_create_booking_invite(self.appt_hr_call)
        # Simulate a pre-per-invite (bare) marker from before v17.0.24.12.0.
        applicant.message_post(body='Queued. <!-- call-invite-sent-marker -->')
        self.assertTrue(applicant._has_call_invite_sent_marker(invite),
            "a legacy bare marker still reads as sent (backward-compat)")

    def _book(self, applicant, appt_type):
        """Mint an invite and create a booked call event for ``applicant``."""
        invite = applicant._get_or_create_booking_invite(appt_type)
        start = datetime.now() + timedelta(days=1)
        return self.CalendarEvent.create({
            'name': 'Booked', 'start': start,
            'stop': start + timedelta(minutes=30),
            'appointment_type_id': appt_type.id,
            'appointment_invite_id': invite.id,
            'partner_ids': [(6, 0, applicant.partner_id.ids)]
                           if applicant.partner_id else False,
        })

    def test_mark_attended_and_no_show(self):
        # v17.0.24.13.0 — outcome is set on the booked call event; the buttons
        # require a booking (they are only shown when call_status == 'booked').
        self._enable(self.job_designer, self.appt_hr_call)
        a = self._make_applicant('Clara E3 CS', self.job_designer, self.stage_call)
        event_a = self._book(a, self.appt_hr_call)
        a.action_mark_attended()
        self.assertEqual(event_a.call_outcome, 'attended',
            "outcome is recorded on the booked call event")
        a.invalidate_recordset(['call_status', 'call_outcome'])
        self.assertEqual(a.call_status, 'attended')
        b = self._make_applicant('Diana E3 CS', self.job_designer, self.stage_call)
        self._book(b, self.appt_hr_call)
        before = self.env['mail.activity'].search_count([
            ('res_id', '=', b.id), ('res_model', '=', 'hr.applicant')])
        b.action_mark_no_show()
        b.invalidate_recordset(['call_status'])
        self.assertEqual(b.call_status, 'no_show')
        after = self.env['mail.activity'].search_count([
            ('res_id', '=', b.id), ('res_model', '=', 'hr.applicant')])
        self.assertGreater(after, before,
            "Mark no-show must schedule a recruiter follow-up activity.")

    def test_mark_attended_requires_a_booked_call(self):
        # No booking → the button action raises instead of silently setting a
        # per-applicant outcome (the buttons are hidden in this state anyway).
        self._enable(self.job_designer, self.appt_hr_call)
        a = self._make_applicant('Nora E3 CS', self.job_designer, self.stage_call)
        with self.assertRaises(UserError):
            a.action_mark_attended()

    def test_outcome_is_per_call_stage(self):
        # The reported bug: mark the FIRST call attended, move to a SECOND call
        # stage → the chip there must NOT stay 'attended'.
        self._enable(self.job_designer, self.appt_hr_call)
        stage_call_2 = self.Stage.create({
            'name': 'Second call CS4', 'sequence': 37,
            'job_ids': [(6, 0, [self.job_designer.id])]})
        cfg2 = self._get_config(self.job_designer, stage_call_2)
        cfg2.write({'is_call_stage': True,
                    'booking_appointment_type_id': self.appt_tech_call.id})
        applicant = self._make_applicant(
            'Otto E3 CS', self.job_designer, self.stage_call)
        self._book(applicant, self.appt_hr_call)
        applicant.action_mark_attended()
        applicant.invalidate_recordset(['call_status', 'call_outcome', 'stage_id'])
        self.assertEqual(applicant.call_status, 'attended',
            "the first call reads attended while still resolving to its event")
        # Move to the SECOND call stage — a different, unbooked call.
        applicant.stage_id = stage_call_2.id
        applicant.invalidate_recordset(['call_status', 'call_outcome'])
        self.assertNotEqual(applicant.call_status, 'attended',
            "the attended outcome of the first call must NOT mask the second "
            "call stage's own status")
        self.assertEqual(applicant.call_outcome, 'pending',
            "the applicant outcome mirror reads pending on the new call stage")

    # ---- 3.2: booking_url is readable on the applicant ---------------
    def test_booking_url_field_is_readable_post_mint(self):
        self._enable(self.job_designer, self.appt_hr_call)
        applicant = self._make_applicant(
            'Eve E3 CS', self.job_designer, self.stage_call)
        applicant.action_generate_booking_link()
        applicant.invalidate_recordset(['booking_url'])
        self.assertTrue(applicant.booking_url)
        self.assertTrue(applicant.booking_url.startswith('http'))

    # ---- 3.3: generate without a Call Stage raises user-friendly ----
    def test_generate_without_call_stage_raises(self):
        # job has no call stage configured.
        applicant = self._make_applicant(
            'Felix E3 CS', self.job_designer, self.stage_call)
        with self.assertRaises(UserError):
            applicant.action_generate_booking_link()

    # ---- 3.4: call_scheduling_visible toggles per job ----------------
    def test_call_scheduling_visible_only_when_job_has_call_stage(self):
        applicant_no = self._make_applicant(
            'Halyna E3 CS', self.job_engineer)
        self.assertFalse(applicant_no.call_scheduling_visible)
        self._enable(self.job_engineer, self.appt_tech_call)
        applicant_no.invalidate_recordset(['call_scheduling_visible'])
        self.assertTrue(applicant_no.call_scheduling_visible)

    # ---- 3.5: template renders booking_url via object.booking_url ----
    def test_template_body_reads_object_booking_url(self):
        tmpl = self.env.ref(
            'hr_recruitment_call_stage.mail_template_call_invite_generic')
        self.assertIn('object.booking_url', tmpl.body_html or '')

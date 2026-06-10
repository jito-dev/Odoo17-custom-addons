# -*- coding: utf-8 -*-
from datetime import datetime, timedelta

from odoo.tests import tagged

from odoo.addons.hr_recruitment_call_stage.tests.common import CallStageTestCommon

MEET_URL = 'https://meet.google.com/abc-defg-hij'
MEET_URL_2 = 'https://meet.google.com/zzz-yyyy-xxx'


@tagged('post_install', '-at_install')
class TestCallMeetBridge(CallStageTestCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Drive the HR call appointment type through the native Google Meet
        # source (Odoo's Google Calendar sync attaches the Meet conference).
        cls.appt_hr_call.event_videocall_source = 'google_meet'

    # ---- helpers -----------------------------------------------------
    def _enable(self, job, appt_type):
        cfg = self._get_config(job, self.stage_call)
        cfg.write({
            'is_call_stage': True,
            'booking_appointment_type_id': appt_type.id,
        })
        return cfg

    def _booked_applicant(self, name, job, appt_type):
        applicant = self._make_applicant(name, job)
        applicant.stage_id = self.stage_call.id
        invite = applicant._get_or_create_booking_invite(appt_type)
        return applicant, invite

    def _create_event(self, applicant, appt_type, invite, location=MEET_URL, **kw):
        start = datetime.now() + timedelta(days=1)
        vals = {
            'name': 'placeholder',
            'start': start,
            'stop': start + timedelta(minutes=30),
            'appointment_type_id': appt_type.id,
            'appointment_invite_id': invite.id,
            'videocall_location': location,
            'partner_ids': [(6, 0, applicant.partner_id.ids)] if applicant.partner_id else False,
        }
        vals.update(kw)
        return self.CalendarEvent.create(vals)

    # ---- F0: single join link ---------------------------------------
    def test_f0_redirection_equals_location_for_meet(self):
        event = self.CalendarEvent.create({
            'name': 'Meet event',
            'start': datetime.now(),
            'stop': datetime.now() + timedelta(minutes=30),
            'videocall_location': MEET_URL,
        })
        self.assertEqual(event.videocall_source, 'google_meet_rest')
        self.assertEqual(
            event.videocall_redirection, event.videocall_location,
            "Join button (redirection) and body link (location) must be the "
            "same URL for a Google Meet event")

    def test_f0_non_meet_event_untouched(self):
        event = self.CalendarEvent.create({
            'name': 'Discuss event',
            'start': datetime.now(),
            'stop': datetime.now() + timedelta(minutes=30),
        })
        # Default discuss event: redirection points at the Odoo route, not
        # equal to a meet.google.com URL — our override must not touch it.
        self.assertNotEqual(event.videocall_source, 'google_meet_rest')

    # ---- F1: Meet space reuse on the invite --------------------------
    def test_f1_reuse_cached_url_skips_mint(self):
        # The cache/mint reuse is google_meet_integration's REST-mint feature,
        # exercised here with its own source key.
        self.appt_hr_call.event_videocall_source = 'google_meet_rest'
        applicant, invite = self._booked_applicant(
            'Reuse CS', self.job_designer, self.appt_hr_call)
        invite.meet_space_url = MEET_URL
        partner = applicant.partner_id
        start = datetime.now() + timedelta(days=1)
        Service = self.env['google.meet.service'].__class__
        calls = []

        def _boom(self_service, preferred_user):
            calls.append(preferred_user)
            return MEET_URL_2

        from unittest.mock import patch
        with patch.object(Service, '_mint_meet_space', _boom):
            values = self.appt_hr_call._prepare_calendar_event_values(
                1, [], '', 0.5, invite, self.env['res.partner'],
                'Reuse CS', partner, self.env.user, start,
                start + timedelta(minutes=30))
        self.assertEqual(values.get('videocall_location'), MEET_URL,
                         "Cached invite URL must be reused")
        self.assertEqual(calls, [], "No mint when a cached URL exists")

    def test_f1_mint_persists_on_invite(self):
        # REST-mint persistence is google_meet_integration's feature; pin its
        # own source key to exercise it.
        self.appt_hr_call.event_videocall_source = 'google_meet_rest'
        applicant, invite = self._booked_applicant(
            'Mint CS', self.job_designer, self.appt_hr_call)
        self.assertFalse(invite.meet_space_url)
        partner = applicant.partner_id
        start = datetime.now() + timedelta(days=1)
        Service = self.env['google.meet.service'].__class__
        calls = []

        def _mint(self_service, preferred_user):
            calls.append(preferred_user)
            return MEET_URL_2

        from unittest.mock import patch
        with patch.object(Service, '_mint_meet_space', _mint):
            values = self.appt_hr_call._prepare_calendar_event_values(
                1, [], '', 0.5, invite, self.env['res.partner'],
                'Mint CS', partner, self.env.user, start,
                start + timedelta(minutes=30))
        self.assertEqual(values.get('videocall_location'), MEET_URL_2)
        self.assertEqual(len(calls), 1, "Mint exactly once")
        self.assertEqual(invite.meet_space_url, MEET_URL_2,
                         "Minted URL must persist on the invite for reuse")

    # ---- Auto-enable Google Meet source on Call Stage config ---------
    def test_config_forces_google_meet_source(self):
        # A booking type left on the default 'discuss' source must be switched
        # to the native Google Meet source the moment its stage is configured
        # as a Call Stage, so booked calls get a Meet link via Google sync.
        self.appt_hr_call.event_videocall_source = 'discuss'
        self._enable(self.job_designer, self.appt_hr_call)
        self.assertEqual(
            self.appt_hr_call.event_videocall_source, 'google_meet',
            "Enabling a Call Stage must force its booking type to Google Meet")

    def test_config_non_call_stage_leaves_source(self):
        # Touching a config that is NOT a call stage must not rewrite the
        # appointment type's videocall source.
        self.appt_hr_call.event_videocall_source = 'discuss'
        cfg = self._get_config(self.job_designer, self.stage_call)
        cfg.write({'is_call_stage': False,
                   'booking_appointment_type_id': self.appt_hr_call.id})
        self.assertEqual(self.appt_hr_call.event_videocall_source, 'discuss',
                         "Non call-stage config must leave the source alone")

    # ---- F2: cockpit meet_url ----------------------------------------
    def test_f2_meet_url_reads_booked_event(self):
        self._enable(self.job_designer, self.appt_hr_call)
        applicant, invite = self._booked_applicant(
            'Cockpit CS', self.job_designer, self.appt_hr_call)
        self.assertFalse(applicant.meet_url)
        self._create_event(applicant, self.appt_hr_call, invite)
        applicant.invalidate_recordset(['meet_url'])
        self.assertEqual(applicant.meet_url, MEET_URL)

    # ---- F3 / F4: cancel ---------------------------------------------
    def test_f3_cancel_sets_state_and_alerts(self):
        self._enable(self.job_designer, self.appt_hr_call)
        applicant, invite = self._booked_applicant(
            'Cancel CS', self.job_designer, self.appt_hr_call)
        event = self._create_event(applicant, self.appt_hr_call, invite)
        applicant.invalidate_recordset(['call_status'])
        self.assertEqual(applicant.call_status, 'booked')
        before_activities = len(applicant.activity_ids)
        event.action_archive()
        applicant.invalidate_recordset(['call_cancelled', 'call_status', 'activity_ids'])
        self.assertTrue(applicant.call_cancelled)
        self.assertEqual(applicant.call_status, 'cancelled')
        self.assertGreater(len(applicant.activity_ids), before_activities,
                           "Cancel must schedule a recruiter To-Do")

    def test_f3_attended_wins_over_cancelled(self):
        self._enable(self.job_designer, self.appt_hr_call)
        applicant, invite = self._booked_applicant(
            'Won CS', self.job_designer, self.appt_hr_call)
        self._create_event(applicant, self.appt_hr_call, invite)
        applicant.call_cancelled = True
        applicant.call_outcome = 'attended'
        applicant.invalidate_recordset(['call_status'])
        self.assertEqual(applicant.call_status, 'attended',
                         "Recruiter outcome must win over cancelled flag")

    # ---- F3 / F4: reschedule -----------------------------------------
    def test_f3_reschedule_in_place(self):
        self._enable(self.job_designer, self.appt_hr_call)
        applicant, invite = self._booked_applicant(
            'Move CS', self.job_designer, self.appt_hr_call)
        event = self._create_event(applicant, self.appt_hr_call, invite)
        event.start = event.start + timedelta(hours=2)
        applicant.invalidate_recordset(['call_rescheduled', 'call_status', 'call_booked_start'])
        self.assertTrue(applicant.call_rescheduled)
        self.assertEqual(applicant.call_status, 'rescheduled')
        self.assertEqual(applicant.call_booked_start, event.start)

    def test_f3_reschedule_cancel_then_rebook(self):
        self._enable(self.job_designer, self.appt_hr_call)
        applicant, invite = self._booked_applicant(
            'Rebook CS', self.job_designer, self.appt_hr_call)
        event1 = self._create_event(applicant, self.appt_hr_call, invite)
        event1.action_archive()
        applicant.invalidate_recordset(['call_cancelled'])
        self.assertTrue(applicant.call_cancelled)
        # Candidate picks a new slot — native flow creates a new event.
        self._create_event(applicant, self.appt_hr_call, invite)
        applicant.invalidate_recordset(['call_cancelled', 'call_rescheduled', 'call_status'])
        self.assertFalse(applicant.call_cancelled, "Rebook clears cancellation")
        self.assertTrue(applicant.call_rescheduled)
        self.assertEqual(applicant.call_status, 'rescheduled')

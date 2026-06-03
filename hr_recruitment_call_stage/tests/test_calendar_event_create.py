# -*- coding: utf-8 -*-
from datetime import datetime, timedelta

from odoo.tests import tagged

from .common import CallStageTestCommon


@tagged('post_install', '-at_install')
class TestCalendarEventCreate(CallStageTestCommon):
    def _enable(self, job, appt_type):
        cfg = self._get_config(job, self.stage_call)
        cfg.write({
            'is_call_stage': True,
            'booking_appointment_type_id': appt_type.id,
        })
        return cfg

    def _make_booked_applicant(self, name, job, appt_type):
        applicant = self._make_applicant(name, job)
        applicant.stage_id = self.stage_call.id
        # Mint the invite the same way _track_template would in prod —
        # mail tracking is precommit-deferred so we do not get an auto-mint
        # in TransactionCase.
        invite = applicant._get_or_create_booking_invite(appt_type)
        return applicant, invite

    def _create_event(self, applicant, appt_type, invite, **overrides):
        start = datetime.now() + timedelta(days=1)
        vals = {
            'name': 'STOCK PLACEHOLDER — overridden',
            'start': start,
            'stop': start + timedelta(minutes=30),
            'appointment_type_id': appt_type.id,
            'appointment_invite_id': invite.id,
            'partner_ids': [(6, 0, applicant.partner_id.ids)] if applicant.partner_id else False,
        }
        vals.update(overrides)
        return self.CalendarEvent.create(vals)

    def test_create_sets_applicant_and_renames_event(self):
        self._enable(self.job_designer, self.appt_hr_call)
        applicant, invite = self._make_booked_applicant(
            'Erika CS', self.job_designer, self.appt_hr_call)
        event = self._create_event(applicant, self.appt_hr_call, invite)
        self.assertEqual(event.applicant_id, applicant)
        self.assertEqual(event.name, 'Erika CS — HR Call CS')

    def test_create_advances_applicant(self):
        cfg = self._enable(self.job_designer, self.appt_hr_call)
        applicant, invite = self._make_booked_applicant(
            'Felix CS', self.job_designer, self.appt_hr_call)
        self.assertEqual(applicant.stage_id, self.stage_call)
        self._create_event(applicant, self.appt_hr_call, invite)
        applicant.invalidate_recordset(['stage_id'])
        # Etap 8: auto-advance lands on the config's per-(job, stage) paired
        # Call Booked stage, not the legacy global one.
        self.assertEqual(applicant.stage_id, cfg.call_booked_stage_id)
        self.assertNotEqual(applicant.stage_id, self.stage_call_booked)

    def test_race_safety_recruiter_moved_applicant_already(self):
        self._enable(self.job_designer, self.appt_hr_call)
        applicant, invite = self._make_booked_applicant(
            'Galya CS', self.job_designer, self.appt_hr_call)
        # Recruiter moved them out before candidate confirmed.
        other_stage = self.Stage.create({
            'name': 'Hold CS', 'sequence': 31})
        applicant.stage_id = other_stage.id
        before = applicant.stage_id
        self._create_event(applicant, self.appt_hr_call, invite)
        applicant.invalidate_recordset(['stage_id'])
        self.assertEqual(applicant.stage_id, before,
                         "Auto-advance must skip when applicant left Call Stage")

    def test_wrong_appointment_type_does_not_advance(self):
        self._enable(self.job_designer, self.appt_hr_call)
        applicant, _invite = self._make_booked_applicant(
            'Halyna CS', self.job_designer, self.appt_hr_call)
        # Create another invite for the other appointment type so the
        # FK is satisfied, then fire create with appt_tech_call.
        other_invite = applicant._get_or_create_booking_invite(self.appt_tech_call)
        self._create_event(applicant, self.appt_tech_call, other_invite)
        applicant.invalidate_recordset(['stage_id'])
        self.assertEqual(applicant.stage_id, self.stage_call,
                         "Advance only when appt_type matches the config")

    def test_customer_summary_is_candidate_friendly(self):
        self._enable(self.job_designer, self.appt_hr_call)
        applicant, invite = self._make_booked_applicant(
            'Ivan CS', self.job_designer, self.appt_hr_call)
        event = self._create_event(applicant, self.appt_hr_call, invite)
        summary = event._get_customer_summary()
        self.assertIn('Senior Designer CS', summary)
        self.assertNotEqual(summary, event.name,
                            "ICS SUMMARY must differ from in-Odoo event.name")

    def test_customer_description_minimal_layout(self):
        self._enable(self.job_designer, self.appt_hr_call)
        applicant, invite = self._make_booked_applicant(
            'Ivan CS', self.job_designer, self.appt_hr_call)
        event = self._create_event(
            applicant, self.appt_hr_call, invite,
            access_token='tok-warm-123')
        desc = event._get_customer_description()
        # One-line confirmation states the role and ends with "confirmed."
        self.assertIn('Senior Designer CS', desc)
        self.assertIn('role is confirmed.', desc)
        # Position section is present.
        self.assertIn('Position', desc)
        # Self-service links framed under "Need to make a change?" — real URLs
        # carrying the event access token.
        self.assertIn('Need to make a change?', desc)
        self.assertIn('/calendar/view/tok-warm-123', desc)
        self.assertIn('/calendar/tok-warm-123/cancel', desc)
        # The old warm/emoji layout is gone — minimal design only.
        self.assertNotIn("You're all set", desc)
        self.assertNotIn('💡', desc)
        self.assertNotIn('See you soon!', desc)

    def test_description_has_candidate_internal_link(self):
        # Recruiter aid: both the synced HTML body and the plaintext ICS carry
        # a "Candidate (internal): <name>" link to the applicant backend form.
        self._enable(self.job_designer, self.appt_hr_call)
        applicant, invite = self._make_booked_applicant(
            'Marta CS', self.job_designer, self.appt_hr_call)
        event = self._create_event(applicant, self.appt_hr_call, invite)
        backend_link = '/web#id=%s&model=hr.applicant&view_type=form' % (
            applicant.id)
        # Plaintext ICS twin — raw URL (no HTML escaping).
        text = event._get_customer_description()
        self.assertIn('Candidate (internal):', text)
        self.assertIn('Marta CS', text)
        self.assertIn(backend_link, text)
        # Synced HTML body Google Calendar reads (set on the field at create).
        # Markup escapes `&` -> `&amp;` in the href, which browsers decode
        # back, so the link still resolves; assert the escaped form here.
        html_link = backend_link.replace('&', '&amp;')
        self.assertIn('Candidate (internal):', event.description)
        self.assertIn(html_link, event.description)

    def test_customer_description_skips_empty_what_to_expect(self):
        self._enable(self.job_designer, self.appt_hr_call)
        applicant, invite = self._make_booked_applicant(
            'Karina CS', self.job_designer, self.appt_hr_call)
        event = self._create_event(applicant, self.appt_hr_call, invite)
        # No what_to_expect configured -> the section is omitted entirely,
        # no orphan header.
        self.assertNotIn('What to expect', event._get_customer_description())

    def test_customer_description_shows_what_to_expect(self):
        cfg = self._enable(self.job_designer, self.appt_hr_call)
        cfg.what_to_expect = 'A short intro chat\nYour recent projects'
        applicant, invite = self._make_booked_applicant(
            'Lev CS', self.job_designer, self.appt_hr_call)
        event = self._create_event(applicant, self.appt_hr_call, invite)
        desc = event._get_customer_description()
        self.assertIn('What to expect', desc)
        self.assertIn('A short intro chat', desc)
        self.assertIn('Your recent projects', desc)

    def test_reschedule_logs_chatter(self):
        self._enable(self.job_designer, self.appt_hr_call)
        applicant, invite = self._make_booked_applicant(
            'Julia CS', self.job_designer, self.appt_hr_call)
        event = self._create_event(applicant, self.appt_hr_call, invite)
        before_msg_count = len(applicant.message_ids)
        event.start = event.start + timedelta(hours=2)
        applicant.invalidate_recordset(['message_ids'])
        self.assertGreater(len(applicant.message_ids), before_msg_count,
                           "Reschedule must post a chatter note on applicant")

    def test_unrelated_event_left_alone(self):
        event = self.CalendarEvent.create({
            'name': 'Random Meeting CS',
            'start': datetime.now(),
            'stop': datetime.now() + timedelta(minutes=15),
        })
        self.assertEqual(event.name, 'Random Meeting CS')
        self.assertFalse(event.applicant_id)

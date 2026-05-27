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
        self._enable(self.job_designer, self.appt_hr_call)
        applicant, invite = self._make_booked_applicant(
            'Felix CS', self.job_designer, self.appt_hr_call)
        self.assertEqual(applicant.stage_id, self.stage_call)
        self._create_event(applicant, self.appt_hr_call, invite)
        applicant.invalidate_recordset(['stage_id'])
        self.assertEqual(applicant.stage_id, self.stage_call_booked)

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

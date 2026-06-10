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

    def test_mark_attended_and_no_show(self):
        self._enable(self.job_designer, self.appt_hr_call)
        a = self._make_applicant('Clara E3 CS', self.job_designer, self.stage_call)
        a.action_mark_attended()
        self.assertEqual(a.call_status, 'attended')
        b = self._make_applicant('Diana E3 CS', self.job_designer, self.stage_call)
        before = self.env['mail.activity'].search_count([
            ('res_id', '=', b.id), ('res_model', '=', 'hr.applicant')])
        b.action_mark_no_show()
        self.assertEqual(b.call_status, 'no_show')
        after = self.env['mail.activity'].search_count([
            ('res_id', '=', b.id), ('res_model', '=', 'hr.applicant')])
        self.assertGreater(after, before,
            "Mark no-show must schedule a recruiter follow-up activity.")

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

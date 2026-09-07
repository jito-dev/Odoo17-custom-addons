# -*- coding: utf-8 -*-
"""v17.0.28.3.0 — a database fault is never softened into a business answer.

v17.0.28.2.0 established the rule at one site, after a production incident:
`_track_template` caught the failing invite mint with a bare `except
Exception` and then kept working on the same cursor. PostgreSQL aborts the
whole transaction on error, so every line of the recovery path raised
`InFailedSqlTransaction` and REPLACED the real cause — that is how `relation
... does not exist` reached a recruiter as an opaque RPC_ERROR.

The rule was applied once; five other suppressions had the identical shape.
This file pins all of them, each as a pair: a database fault propagates, and
the graceful degradation everything else relies on is left intact.

The two must be tested together. A guard that re-raises everything would pass
the first assertion of each pair and quietly undo the reason the suppression
exists.
"""
from datetime import datetime, timedelta
from unittest.mock import patch

import psycopg2

from odoo.tests import tagged

from .common import CallStageTestCommon


@tagged('post_install', '-at_install')
class TestDatabaseFaultPassthrough(CallStageTestCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # A real, active user: `env.user` is OdooBot on a test run and is
        # archived, so writing it to `staff_user_ids` reads back empty and the
        # branches under test are never entered.
        cls.interviewer = cls.env['res.users'].create({
            'name': 'Ivy Interviewer CS',
            'login': 'cs_ivy_dbfault',
            'email': 'cs_ivy_dbfault@example.com',
        })
        cls.appt_hr_call.staff_user_ids = [(6, 0, [cls.interviewer.id])]
        cls.template = cls.env['mail.template'].create({
            'name': 'DB Fault Call Invite CS',
            'model_id': cls.env.ref('hr_recruitment.model_hr_applicant').id,
            'subject': 'Book your call',
            'body_html': '<a t-att-href="ctx.get(\'booking_url\') or \'\'">link</a>',
        })

    def setUp(self):
        super().setUp()
        self.cfg = self._get_config(self.job_designer, self.stage_call)
        self.cfg.write({
            'is_call_stage': True,
            'booking_appointment_type_id': self.appt_hr_call.id,
            'mail_template_id': self.template.id,
        })

    def _book(self, applicant):
        """Mint an invite and create a booked call event, as `test_etap3` does.

        `action_mark_no_show` refuses before it reaches the guarded block when
        the applicant has no booked call.
        """
        invite = applicant._get_or_create_booking_invite(self.appt_hr_call)
        start = datetime.now() + timedelta(days=1)
        return self.CalendarEvent.create({
            'name': 'Booked', 'start': start,
            'stop': start + timedelta(minutes=30),
            'appointment_type_id': self.appt_hr_call.id,
            'appointment_invite_id': invite.id,
            'partner_ids': [(6, 0, applicant.partner_id.ids)]
                           if applicant.partner_id else False,
        })

    @staticmethod
    def _db_fault():
        """The shape of the fault that caused the production incident."""
        return psycopg2.errors.UndefinedTable(
            'relation "hr_job_stage_config_call_staff_user_rel" does not exist')

    # ------------------------------------------------------------------
    # Send-time guard — the most consequential of the six
    # ------------------------------------------------------------------
    def test_render_body_propagates_a_database_fault(self):
        """An empty render is read as "this template has no booking button".

        `_call_stage_booking_button_ok` turns that into a permanently
        suppressed invite plus a to-do telling the recruiter to fix their
        template. Reporting a database fault as a broken template sends them
        to the one place the problem is not.
        """
        applicant = self._make_applicant('Render Fault CS', self.job_designer)
        with patch.object(type(self.template), '_render_field',
                          side_effect=self._db_fault()):
            with self.assertRaises(psycopg2.Error):
                applicant._call_stage_render_body(self.template, 'https://x/book/1')

    def test_render_body_still_degrades_on_anything_else(self):
        applicant = self._make_applicant('Render Soft CS', self.job_designer)
        with patch.object(type(self.template), '_render_field',
                          side_effect=ValueError('qweb is unhappy')):
            self.assertEqual(
                applicant._call_stage_render_body(self.template, 'https://x/book/1'),
                '',
                "A template that cannot render must still gate the send.")

    # ------------------------------------------------------------------
    # The recruiter-alert path itself
    # ------------------------------------------------------------------
    def test_alert_recruiter_propagates_a_database_fault(self):
        applicant = self._make_applicant('Alert Fault CS', self.job_designer)
        with patch.object(type(applicant), 'activity_schedule',
                          side_effect=self._db_fault()):
            with self.assertRaises(psycopg2.Error):
                applicant._call_stage_alert_recruiter('booking link is broken')

    def test_alert_recruiter_still_swallows_anything_else(self):
        """The alert is the last line of defence; it may not raise on its own."""
        applicant = self._make_applicant('Alert Soft CS', self.job_designer)
        with patch.object(type(applicant), 'activity_schedule',
                          side_effect=ValueError('activity types are down')):
            self.assertFalse(
                applicant._call_stage_alert_recruiter('booking link is broken'),
                "A failed alert returns an empty activity, never an exception.")

    # ------------------------------------------------------------------
    # No-show follow-up
    # ------------------------------------------------------------------
    def test_no_show_propagates_a_database_fault(self):
        applicant = self._make_applicant(
            'No Show Fault CS', self.job_designer, self.stage_call)
        self._book(applicant)
        with patch.object(type(applicant), 'activity_schedule',
                          side_effect=self._db_fault()):
            with self.assertRaises(psycopg2.Error):
                applicant.action_mark_no_show()

    def test_no_show_still_records_the_outcome_on_anything_else(self):
        applicant = self._make_applicant(
            'No Show Soft CS', self.job_designer, self.stage_call)
        self._book(applicant)
        with patch.object(type(applicant), 'activity_schedule',
                          side_effect=ValueError('activity types are down')):
            self.assertTrue(
                applicant.action_mark_no_show(),
                "Marking the no-show must survive a failed follow-up to-do.")

    # ------------------------------------------------------------------
    # The two config-form previews
    # ------------------------------------------------------------------
    def test_slot_count_preview_propagates_a_database_fault(self):
        with patch.object(type(self.appt_hr_call), '_get_appointment_slots',
                          side_effect=self._db_fault()):
            self.cfg.invalidate_recordset(['call_free_slot_count_7d'])
            with self.assertRaises(psycopg2.Error):
                self.cfg.call_free_slot_count_7d

    def test_slot_count_preview_still_degrades_on_anything_else(self):
        with patch.object(type(self.appt_hr_call), '_get_appointment_slots',
                          side_effect=ValueError('slot generation is unhappy')):
            self.cfg.invalidate_recordset(['call_free_slot_count_7d'])
            self.assertEqual(
                self.cfg.call_free_slot_count_7d, -1,
                "The dialog shows 'unknown', it does not break.")

    def test_availability_preview_propagates_a_database_fault(self):
        with patch.object(type(self.cfg), '_call_slot_counts_by_day',
                          side_effect=self._db_fault()):
            self.cfg.invalidate_recordset(['call_availability_7d'])
            with self.assertRaises(psycopg2.Error):
                self.cfg.call_availability_7d

    def test_availability_preview_still_degrades_on_anything_else(self):
        with patch.object(type(self.cfg), '_call_slot_counts_by_day',
                          side_effect=ValueError('slot generation is unhappy')):
            self.cfg.invalidate_recordset(['call_availability_7d'])
            payload = self.cfg.call_availability_7d
        self.assertIn(
            'compute_failed', payload or '',
            "The 7-day grid reports itself unavailable, it does not break.")

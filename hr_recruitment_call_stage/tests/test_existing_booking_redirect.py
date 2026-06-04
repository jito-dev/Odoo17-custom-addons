# -*- coding: utf-8 -*-
"""Coverage for the "returning candidate sees their existing booking" feature
(v17.0.19.0.0).

The public controller (``appointment_type_page``) short-circuits a candidate
who re-opens the ``/book`` link after booking to their existing booking's
confirmation page. The HTTP round-trip is heavy/brittle to stand up, so we pin
the decision the redirect hinges on: ``hr.applicant._get_upcoming_booked_call_event``
— it must return the live upcoming event, and nothing for the past / cancelled
/ never-booked cases (those fall through to the native slot picker).
"""
from datetime import datetime, timedelta

from odoo.tests import tagged

from .common import CallStageTestCommon


@tagged('post_install', '-at_install')
class TestExistingBookingRedirect(CallStageTestCommon):
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
        invite = applicant._get_or_create_booking_invite(appt_type)
        return applicant, invite

    def _create_event(self, applicant, appt_type, invite, start):
        return self.CalendarEvent.create({
            'name': 'STOCK PLACEHOLDER — overridden',
            'start': start,
            'stop': start + timedelta(minutes=30),
            'appointment_type_id': appt_type.id,
            'appointment_invite_id': invite.id,
            'partner_ids': [(6, 0, applicant.partner_id.ids)]
            if applicant.partner_id else False,
        })

    def test_returns_upcoming_event(self):
        self._enable(self.job_designer, self.appt_hr_call)
        applicant, invite = self._make_booked_applicant(
            'Olena CS', self.job_designer, self.appt_hr_call)
        event = self._create_event(
            applicant, self.appt_hr_call, invite,
            datetime.now() + timedelta(days=1))
        self.assertEqual(
            applicant._get_upcoming_booked_call_event(invite=invite), event)

    def test_returns_empty_when_never_booked(self):
        self._enable(self.job_designer, self.appt_hr_call)
        applicant, invite = self._make_booked_applicant(
            'Petro CS', self.job_designer, self.appt_hr_call)
        self.assertFalse(
            applicant._get_upcoming_booked_call_event(invite=invite))

    def test_ignores_past_event(self):
        self._enable(self.job_designer, self.appt_hr_call)
        applicant, invite = self._make_booked_applicant(
            'Rita CS', self.job_designer, self.appt_hr_call)
        self._create_event(
            applicant, self.appt_hr_call, invite,
            datetime.now() - timedelta(days=1))
        self.assertFalse(
            applicant._get_upcoming_booked_call_event(invite=invite),
            "a past call must not short-circuit a fresh booking")

    def test_ignores_cancelled_event(self):
        """A cancelled (archived) event must not block re-booking."""
        self._enable(self.job_designer, self.appt_hr_call)
        applicant, invite = self._make_booked_applicant(
            'Sofia CS', self.job_designer, self.appt_hr_call)
        event = self._create_event(
            applicant, self.appt_hr_call, invite,
            datetime.now() + timedelta(days=1))
        event.action_archive()
        self.assertFalse(
            applicant._get_upcoming_booked_call_event(invite=invite),
            "an archived/cancelled event must fall through to the picker")

    def test_returns_nearest_when_multiple(self):
        self._enable(self.job_designer, self.appt_hr_call)
        applicant, invite = self._make_booked_applicant(
            'Taras CS', self.job_designer, self.appt_hr_call)
        far = self._create_event(
            applicant, self.appt_hr_call, invite,
            datetime.now() + timedelta(days=5))
        near = self._create_event(
            applicant, self.appt_hr_call, invite,
            datetime.now() + timedelta(days=2))
        self.assertEqual(
            applicant._get_upcoming_booked_call_event(invite=invite), near,
            "must surface the soonest upcoming call")
        self.assertNotEqual(
            applicant._get_upcoming_booked_call_event(invite=invite), far)

    def test_empty_without_invite(self):
        applicant = self._make_applicant('Uma CS', self.job_designer)
        self.assertFalse(
            applicant._get_upcoming_booked_call_event(
                invite=self.env['appointment.invite']))

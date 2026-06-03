# -*- coding: utf-8 -*-
"""Unit coverage for the Call Stage booking-form prefill/lock controller.

The full HTTP round-trip (rendering the form, posting a booking) needs a
fully bookable appointment type with staff availability, which is heavy and
brittle to set up. These tests instead pin the decision logic that drives
both the read-only flags and the server-side enforcement: the field map
(which card field feeds which form field) and the failed-redirect guard that
gates write-back. Those are the parts most likely to regress.
"""
from odoo.addons.hr_recruitment_call_stage.controllers.main import (
    CallStageAppointmentController,
)

from .common import CallStageTestCommon


class _FakeResponse:
    def __init__(self, location):
        self.location = location


class TestBookingPrefill(CallStageTestCommon):

    def test_field_map_name_from_partner_name_only(self):
        """Name must come from ``partner_name`` (a person), never ``name``."""
        applicant = self.Applicant.create({
            'name': 'Application for Senior Designer',  # subject, not a person
            'job_id': self.job_designer.id,
        })
        values = CallStageAppointmentController._call_stage_field_map(applicant)
        # partner_name empty -> name field stays empty (editable + write-back),
        # the application subject is never leaked as the candidate's name.
        self.assertEqual(values['name'], '')

    def test_field_map_present_values(self):
        applicant = self.Applicant.create({
            'name': 'Subject',
            'partner_name': 'Jane Candidate',
            'email_from': 'jane@example.com',
            'partner_phone': '+1 605 555 0100',
            'job_id': self.job_designer.id,
        })
        values = CallStageAppointmentController._call_stage_field_map(applicant)
        self.assertEqual(values['name'], 'Jane Candidate')
        self.assertEqual(values['email'], 'jane@example.com')
        self.assertEqual(values['phone'], '+1 605 555 0100')

    def test_field_map_phone_falls_back_to_mobile(self):
        applicant = self.Applicant.create({
            'name': 'Subject',
            'partner_name': 'Mobile Only',
            'partner_mobile': '+1 605 555 0199',
            'job_id': self.job_designer.id,
        })
        values = CallStageAppointmentController._call_stage_field_map(applicant)
        self.assertEqual(values['phone'], '+1 605 555 0199')

    def test_failed_redirect_guard(self):
        guard = CallStageAppointmentController._call_stage_is_failed_redirect
        self.assertTrue(guard(_FakeResponse(
            '/appointment/5?date_time=...&state=failed-staff-user')))
        self.assertTrue(guard(_FakeResponse('/appointment/5?state=failed-resource')))
        self.assertFalse(guard(_FakeResponse('/calendar/view/abc123')))
        self.assertFalse(guard(_FakeResponse('')))

    def test_messenger_from_card_present(self):
        applicant = self.Applicant.create({
            'name': 'Subject',
            'job_id': self.job_designer.id,
            'messenger_type': 'telegram',
            'messenger_value': '@jane',
        })
        m_type, m_value = (
            CallStageAppointmentController._call_stage_messenger_from_card(applicant))
        self.assertEqual(m_type, 'telegram')
        self.assertEqual(m_value, '@jane')

    def test_messenger_from_card_empty(self):
        """No value -> treated as empty (asked for on the form)."""
        applicant = self.Applicant.create({
            'name': 'Subject',
            'job_id': self.job_designer.id,
        })
        self.assertEqual(
            CallStageAppointmentController._call_stage_messenger_from_card(applicant),
            ('', ''))

    def test_messenger_type_without_value_is_empty(self):
        """A stray type with no value must not count as a present contact."""
        applicant = self.Applicant.create({
            'name': 'Subject',
            'job_id': self.job_designer.id,
            'messenger_type': 'whatsapp',
        })
        _m_type, m_value = (
            CallStageAppointmentController._call_stage_messenger_from_card(applicant))
        self.assertEqual(m_value, '', "no value -> not lockable/present")


class TestSkipDetailsDecision(CallStageTestCommon):
    """Pin the decision that drives skipping the public "details" step.

    The HTTP round-trip (slot click -> /info -> redirect to confirmation) is
    heavy/brittle to set up, so we test the pure predicate that gates it:
    ``_call_stage_should_skip_details``. Skipping must happen ONLY when the
    card holds the full identity AND the type asks nothing else.
    """

    # v17.0.13.0.0: a present-on-card messenger contact is also required for
    # the details step to be skippable (an empty one must be collected).
    ALL_LOCKED = {'name': True, 'email': True, 'phone': True, 'messenger': True}

    def setUp(self):
        super().setUp()
        self.should_skip = CallStageAppointmentController._call_stage_should_skip_details
        self.applicant = self.Applicant.create({
            'name': 'Subject',
            'partner_name': 'Full Candidate',
            'email_from': 'full@example.com',
            'partner_phone': '+1 605 555 0100',
            'job_id': self.job_designer.id,
        })

    def test_skip_when_full_identity_and_no_questions_or_guests(self):
        self.assertTrue(self.should_skip(
            self.applicant, self.appt_hr_call, self.ALL_LOCKED))

    def test_no_skip_without_applicant(self):
        empty = self.env['hr.applicant']
        self.assertFalse(self.should_skip(
            empty, self.appt_hr_call, self.ALL_LOCKED))

    def test_no_skip_without_appointment_type(self):
        self.assertFalse(self.should_skip(
            self.applicant, self.env['appointment.type'], self.ALL_LOCKED))

    def test_no_skip_when_any_field_missing(self):
        for missing in ('name', 'email', 'phone', 'messenger'):
            locked = dict(self.ALL_LOCKED, **{missing: False})
            self.assertFalse(
                self.should_skip(self.applicant, self.appt_hr_call, locked),
                f"must not skip when '{missing}' is not locked")

    def test_no_skip_when_type_has_custom_questions(self):
        self.env['appointment.question'].create({
            'name': 'Portfolio link?',
            'question_type': 'char',
            'appointment_type_id': self.appt_hr_call.id,
        })
        self.assertFalse(self.should_skip(
            self.applicant, self.appt_hr_call, self.ALL_LOCKED))

    def test_no_skip_when_type_allows_guests(self):
        self.appt_hr_call.allow_guests = True
        self.assertFalse(self.should_skip(
            self.applicant, self.appt_hr_call, self.ALL_LOCKED))

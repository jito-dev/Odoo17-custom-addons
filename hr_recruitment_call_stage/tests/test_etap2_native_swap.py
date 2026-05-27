# -*- coding: utf-8 -*-
"""Etap 2 (v17.0.2.0.0) — regression tests for the native-model swap.

Replaces our removed `hr.applicant.booking.invite` join model with
`appointment.invite.applicant_id` shipped by `appointment_hr_recruitment`.
"""
from odoo.tests import tagged

from .common import CallStageTestCommon


@tagged('post_install', '-at_install')
class TestEtap2NativeSwap(CallStageTestCommon):
    def _enable(self, job, appt_type):
        cfg = self._get_config(job, self.stage_call)
        cfg.write({
            'is_call_stage': True,
            'booking_appointment_type_id': appt_type.id,
        })
        return cfg

    # ---- 2.1: dropped model no longer registered --------------------
    def test_legacy_booking_invite_model_is_gone(self):
        self.assertNotIn('hr.applicant.booking.invite', self.env.registry,
            "Legacy join model must be removed from the registry after "
            "Etap 2 native swap.")

    # ---- 2.2: invite minted on native field, not via join -----------
    def test_invite_minted_carries_applicant_natively(self):
        self._enable(self.job_designer, self.appt_hr_call)
        applicant = self._make_applicant(
            'Anna E2 CS', self.job_designer, self.stage_call)
        invite = applicant._get_or_create_booking_invite(self.appt_hr_call)
        self.assertEqual(invite.applicant_id, applicant,
            "Native `appointment.invite.applicant_id` must be set on mint.")
        self.assertIn(self.appt_hr_call, invite.appointment_type_ids)
        self.assertTrue(invite.book_url)

    # ---- 2.3: re-mint returns the existing invite -------------------
    def test_remint_is_idempotent(self):
        self._enable(self.job_designer, self.appt_hr_call)
        applicant = self._make_applicant(
            'Boris E2 CS', self.job_designer, self.stage_call)
        invite_a = applicant._get_or_create_booking_invite(self.appt_hr_call)
        invite_b = applicant._get_or_create_booking_invite(self.appt_hr_call)
        self.assertEqual(invite_a, invite_b)
        # Search must still find exactly one row per (applicant, type).
        all_invites = self.AppointmentInvite.sudo().search([
            ('applicant_id', '=', applicant.id),
            ('appointment_type_ids', 'in', self.appt_hr_call.ids),
        ])
        self.assertEqual(len(all_invites), 1)

    # ---- 2.4: calendar.event.applicant_id resolves natively ---------
    def test_calendar_event_applicant_id_is_native_related(self):
        # Our module no longer declares the field; it must come from
        # `appointment_hr_recruitment` (related, stored).
        field = self.CalendarEvent._fields.get('applicant_id')
        self.assertIsNotNone(field, "applicant_id must exist on calendar.event")
        # Native ships it as a related field via appointment_invite_id.
        self.assertEqual(field.related, ('appointment_invite_id', 'applicant_id'))

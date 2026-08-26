# -*- coding: utf-8 -*-
"""v17.0.25.0.0 — "Who runs the call" (design variant C).

Covers the pool boundary (the appointment type owns bookable staff; the stage
config may only select a subset), the three assignment modes, and how those
reach the per-candidate ``appointment.invite``.
"""
import json

from odoo.exceptions import ValidationError
from odoo.tests.common import tagged

from .common import CallStageTestCommon


@tagged('post_install', '-at_install')
class TestCallAssignMode(CallStageTestCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.interviewer_a = cls.env['res.users'].create({
            'name': 'Interviewer A', 'login': 'cs_interviewer_a',
            'email': 'cs_a@example.com',
        })
        cls.interviewer_b = cls.env['res.users'].create({
            'name': 'Interviewer B', 'login': 'cs_interviewer_b',
            'email': 'cs_b@example.com',
        })
        cls.outsider = cls.env['res.users'].create({
            'name': 'Outsider', 'login': 'cs_outsider',
            'email': 'cs_out@example.com',
        })
        # The pool lives on the appointment type — never written from the config.
        cls.appt_hr_call.staff_user_ids = [
            (6, 0, [cls.interviewer_a.id, cls.interviewer_b.id])]

    def _call_config(self):
        cfg = self._get_config(self.job_designer, self.stage_call)
        cfg.write({
            'is_call_stage': True,
            'booking_appointment_type_id': self.appt_hr_call.id,
        })
        return cfg

    # ------------------------------------------------------------------
    # Pool boundary
    # ------------------------------------------------------------------
    def test_pool_is_the_appointment_type_staff(self):
        cfg = self._call_config()
        self.assertEqual(
            cfg.call_staff_pool_ids, self.appt_hr_call.staff_user_ids,
            "The pool must mirror the appointment type's staff, not a copy.")

    def test_cannot_pick_someone_outside_the_pool(self):
        cfg = self._call_config()
        with self.assertRaises(ValidationError):
            cfg.call_staff_user_ids = [(6, 0, [self.outsider.id])]

    def test_config_never_writes_back_to_the_pool(self):
        """The v17.0.24.0.0 removal of the UNION sync must stay removed."""
        cfg = self._call_config()
        cfg.call_staff_user_ids = [(6, 0, [self.interviewer_a.id])]
        self.assertEqual(
            self.appt_hr_call.staff_user_ids,
            self.interviewer_a | self.interviewer_b,
            "Selecting a subset must not shrink or grow the type's pool.")

    def test_changing_type_prunes_stale_selection(self):
        cfg = self._call_config()
        cfg.call_staff_user_ids = [(6, 0, [self.interviewer_a.id])]
        cfg.booking_appointment_type_id = self.appt_tech_call
        self.assertFalse(
            cfg.call_staff_user_ids,
            "Switching to a type with an empty pool must clear the stale "
            "selection instead of raising about a field nobody touched.")

    # ------------------------------------------------------------------
    # Modes
    # ------------------------------------------------------------------
    def test_this_person_rejects_two_people(self):
        cfg = self._call_config()
        cfg.call_assign_mode = 'this_person'
        with self.assertRaises(ValidationError):
            cfg.call_staff_user_ids = [
                (6, 0, [self.interviewer_a.id, self.interviewer_b.id])]

    def test_effective_staff_falls_back_to_whole_pool(self):
        cfg = self._call_config()
        self.assertFalse(cfg.call_staff_user_ids)
        self.assertEqual(
            cfg._call_effective_staff(), self.appt_hr_call.staff_user_ids,
            "An empty selection must mean the whole pool, like the invite does.")

    def test_invite_values_pin_named_person(self):
        cfg = self._call_config()
        cfg.call_assign_mode = 'this_person'
        cfg.call_staff_user_ids = [(6, 0, [self.interviewer_a.id])]
        vals = cfg._call_invite_values()
        self.assertEqual(vals['resources_choice'], 'specific_resources')
        self.assertEqual(
            vals['staff_user_ids'], [(6, 0, [self.interviewer_a.id])])

    def test_invite_values_anyone_free_keeps_pool_open(self):
        cfg = self._call_config()
        cfg.call_assign_mode = 'anyone_free'
        vals = cfg._call_invite_values()
        self.assertEqual(vals['resources_choice'], 'all_assigned_resources')
        self.assertNotIn(
            'staff_user_ids', vals,
            "With no explicit subset the invite must not pin anyone.")

    # ------------------------------------------------------------------
    # End-to-end: the mode reaches the candidate's invite
    # ------------------------------------------------------------------
    def test_minted_invite_carries_the_named_interviewer(self):
        cfg = self._call_config()
        cfg.call_assign_mode = 'this_person'
        cfg.call_staff_user_ids = [(6, 0, [self.interviewer_b.id])]

        applicant = self._make_applicant(
            'Assign Mode Candidate', self.job_designer, self.stage_call)
        invite = applicant._get_or_create_booking_invite(self.appt_hr_call)

        self.assertTrue(invite, "An invite should have been minted.")
        self.assertEqual(invite.resources_choice, 'specific_resources')
        self.assertEqual(
            invite.staff_user_ids, self.interviewer_b,
            "The stage's named interviewer must reach the candidate's invite.")

    def test_minted_invite_survives_an_empty_selection(self):
        cfg = self._call_config()
        cfg.call_assign_mode = 'applicant_picks'
        applicant = self._make_applicant(
            'Picks Candidate', self.job_designer, self.stage_call)
        invite = applicant._get_or_create_booking_invite(self.appt_hr_call)
        self.assertTrue(invite)
        self.assertEqual(invite.resources_choice, 'all_assigned_resources')


@tagged('post_install', '-at_install')
class TestAvailabilityPreview(CallStageTestCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.interviewer = cls.env['res.users'].create({
            'name': 'Preview Interviewer', 'login': 'cs_preview_user',
            'email': 'cs_preview@example.com',
        })

    def _call_config(self, with_staff=True):
        cfg = self._get_config(self.job_designer, self.stage_call)
        if with_staff:
            self.appt_hr_call.staff_user_ids = [(6, 0, [self.interviewer.id])]
        cfg.write({
            'is_call_stage': True,
            'booking_appointment_type_id': self.appt_hr_call.id,
        })
        return cfg

    def test_payload_has_seven_days(self):
        cfg = self._call_config()
        payload = json.loads(cfg.call_availability_7d)
        self.assertEqual(len(payload['days']), 7)
        for day in payload['days']:
            self.assertIn(day['level'], ('none', 'few', 'ok'))
            self.assertIn('date', day)

    def test_no_staff_is_reported_not_crashed(self):
        cfg = self._call_config(with_staff=False)
        self.appt_hr_call.staff_user_ids = [(5, 0, 0)]
        cfg.invalidate_recordset(['call_availability_7d'])
        payload = json.loads(cfg.call_availability_7d)
        self.assertEqual(payload.get('error'), 'no_staff')

    def test_payload_is_untrusted_when_calendar_not_connected(self):
        """The whole point: an unsynced calendar cannot report busy time, so
        the count must not be presented as verified.

        Skipped where `google_calendar` is absent — it is not a dependency of
        this module, and `test_trust_degrades_gracefully_without_google` covers
        that case instead.
        """
        cfg = self._call_config()
        if not hasattr(self.interviewer, 'is_google_calendar_synced'):
            self.skipTest("google_calendar is not installed on this database")
        self.assertFalse(self.interviewer.is_google_calendar_synced())
        payload = json.loads(cfg.call_availability_7d)
        self.assertFalse(
            payload['trusted'],
            "An unsynced interviewer must mark the preview untrusted.")

    def test_trust_degrades_gracefully_without_google(self):
        """`google_calendar` is NOT a dependency: the preview must still build,
        and must not report every interviewer as unsynced on a database that
        never had Google."""
        cfg = self._call_config()
        self.assertTrue(
            cfg._call_user_calendar_synced(self.interviewer)
            or hasattr(self.interviewer, 'is_google_calendar_synced'),
            "Without google_calendar installed the helper must report synced.")
        payload = json.loads(cfg.call_availability_7d)
        self.assertIn('trusted', payload)
        self.assertEqual(len(payload['days']), 7)

    def test_not_a_call_stage_yields_no_payload(self):
        cfg = self._get_config(self.job_designer, self.stage_call)
        cfg.is_call_stage = False
        self.assertFalse(cfg.call_availability_7d)

    def test_work_hours_warning_fires_when_disabled(self):
        cfg = self._call_config()
        self.appt_hr_call.work_hours_activated = False
        cfg.invalidate_recordset(['call_warn_work_hours_off'])
        self.assertTrue(cfg.call_warn_work_hours_off)


@tagged('post_install', '-at_install')
class TestPoolUnderRecordRules(CallStageTestCommon):
    """Regression: the interviewer dropdown came back empty for recruiters.

    Stock `appointment.type` ships a record rule (`appointment.type: apt user
    rule`) limiting an Appointment User to types they created, or are staff on.
    A recruiter opening a stage wired to a COLLEAGUE's type therefore cannot
    read that type — and a plain `related` pool field raised AccessError, which
    the web client surfaced as "no users to pick".

    The pool is reference data (which users are bookable), so it is read with
    sudo. Writing to the pool remains impossible from this model.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.other_interviewer = cls.env['res.users'].create({
            'name': 'Someone Else', 'login': 'cs_someone_else',
            'email': 'cs_else@example.com',
        })
        groups = cls.env.ref('hr_recruitment.group_hr_recruitment_user')
        appt_group = cls.env.ref(
            'appointment.group_appointment_user', raise_if_not_found=False)
        if appt_group:
            groups |= appt_group
        cls.recruiter = cls.env['res.users'].create({
            'name': 'Plain Recruiter', 'login': 'cs_plain_recruiter',
            'email': 'cs_recruiter@example.com',
            'groups_id': [(6, 0, groups.ids)],
        })
        # A type owned by someone else: the recruiter is neither creator nor staff.
        cls.appt_hr_call.staff_user_ids = [(6, 0, [cls.other_interviewer.id])]

    def test_pool_is_readable_by_a_recruiter_who_cannot_read_the_type(self):
        cfg = self._get_config(self.job_designer, self.stage_call)
        cfg.write({
            'is_call_stage': True,
            'booking_appointment_type_id': self.appt_hr_call.id,
        })
        cfg_as_recruiter = cfg.with_user(self.recruiter)
        pool = cfg_as_recruiter.call_staff_pool_ids
        self.assertEqual(
            pool, self.other_interviewer,
            "The recruiter must still see who is bookable, even though the "
            "appointment type itself is hidden from them by the stock rule.")

    def test_derived_reads_do_not_raise_for_that_recruiter(self):
        cfg = self._get_config(self.job_designer, self.stage_call)
        cfg.write({
            'is_call_stage': True,
            'booking_appointment_type_id': self.appt_hr_call.id,
        })
        cfg_as_recruiter = cfg.with_user(self.recruiter)
        # None of these may raise AccessError.
        self.assertTrue(cfg_as_recruiter.call_availability_7d)
        self.assertEqual(
            cfg_as_recruiter._call_effective_staff(), self.other_interviewer)
        cfg_as_recruiter.call_warn_work_hours_off  # compute must not raise

# -*- coding: utf-8 -*-
"""v17.0.25.0.0 — "Who runs the call" (design variant C).

Covers the three assignment modes and how they reach the per-candidate
``appointment.invite``, plus how the stage config relates to the appointment
type's bookable staff.

v17.0.26.0.0 amended that relationship: the pool is no longer a *boundary* the
config may only narrow — picking an interviewer who is not bookable yet grows
the type's staff instead of being rejected. The pool tests below were updated
accordingly; ``test_interviewer_pool_grow.py`` owns the full coverage.

v17.0.27.0.0 removed ``call_assign_mode`` altogether: all three of its values
produced the same invite payload once an interviewer was picked, because who
takes the booking is decided by ``appointment.type.assign_method`` — which this
module never wrote. The stage now reports that setting through
``call_assign_hint`` instead of pretending to own it.
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
    # Who runs the call
    # ------------------------------------------------------------------
    def test_pool_is_the_appointment_type_staff(self):
        cfg = self._call_config()
        self.assertEqual(
            cfg.call_staff_pool_ids, self.appt_hr_call.staff_user_ids,
            "Who runs the call must mirror the appointment type's staff, not "
            "a copy of it.")

    def test_effective_staff_is_the_type_staff(self):
        """v17.0.28.0.0 — there is no stage-level subset left to fall back from.

        The stage used to keep its own narrowed list, applied once when the
        candidate's invite was minted; anything that moved afterwards turned it
        back into "anyone free" without saying so.
        """
        cfg = self._call_config()
        self.assertEqual(
            cfg._call_effective_staff(), self.appt_hr_call.staff_user_ids)

    def test_hint_reports_the_single_interviewer(self):
        cfg = self._call_config()
        self.appt_hr_call.staff_user_ids = [(6, 0, [self.interviewer_a.id])]
        cfg.invalidate_recordset(['call_assign_hint'])
        self.assertIn(self.interviewer_a.name, cfg.call_assign_hint or '')

    def test_hint_reports_the_types_assignment_method(self):
        cfg = self._call_config()
        self.appt_hr_call.assign_method = 'time_auto_assign'
        cfg.invalidate_recordset(['call_assign_hint'])
        self.assertIn('Odoo assigns', cfg.call_assign_hint or '')
        self.appt_hr_call.assign_method = 'resource_time'
        cfg.invalidate_recordset(['call_assign_hint'])
        self.assertIn('picks one of', cfg.call_assign_hint or '')

    # ------------------------------------------------------------------
    # The invite carries no staff filter — which is the whole point
    # ------------------------------------------------------------------
    def test_minted_invite_carries_no_staff_filter(self):
        self._call_config()
        applicant = self._make_applicant(
            'No Filter Candidate', self.job_designer, self.stage_call)
        invite = applicant._get_or_create_booking_invite(self.appt_hr_call)
        self.assertTrue(invite, "An invite should have been minted.")
        self.assertFalse(
            invite.staff_user_ids,
            "Pinning people onto the invite freezes them there for the life of "
            "the link; the booking page must read the type instead.")
        self.assertNotIn(
            'filter_staff_user_ids', invite.redirect_url or '',
            "A staff filter in the URL is exactly what stops the booking page "
            "from reading the appointment type live.")

    def test_type_staff_change_reaches_an_existing_invite(self):
        """The gain: a link already in a candidate's inbox follows the type."""
        self._call_config()
        applicant = self._make_applicant(
            'Live Link Candidate', self.job_designer, self.stage_call)
        invite = applicant._get_or_create_booking_invite(self.appt_hr_call)
        self.appt_hr_call.staff_user_ids = [(4, self.outsider.id)]
        invite.invalidate_recordset(['staff_user_ids', 'redirect_url'])
        self.assertFalse(
            invite.staff_user_ids,
            "Nothing on the invite may pin a staff list, or the newcomer would "
            "stay invisible to everyone already holding a link.")
        self.assertIn(
            self.outsider, self.appt_hr_call.staff_user_ids,
            "The type is the single place who-runs-the-call is edited.")

    # ------------------------------------------------------------------
    # Getting a type without leaving the stage
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Sharing a type is now the only coupling left, so it must be visible
    # ------------------------------------------------------------------
    def test_shared_stages_banner_names_every_sibling(self):
        cfg = self._call_config()
        sibling = self._get_config(self.job_engineer, self.stage_call)
        sibling.write({'is_call_stage': True,
                       'booking_appointment_type_id': self.appt_hr_call.id})
        cfg.invalidate_recordset(['call_pool_shared_stages'])
        self.assertIn(
            self.job_engineer.name, cfg.call_pool_shared_stages or '',
            "Before v17.0.28.0.0 only siblings with an empty Interviewer were "
            "listed; every stage on the type is affected by it now.")

    def test_shared_stages_banner_is_silent_for_an_exclusive_type(self):
        cfg = self._call_config()
        cfg.booking_appointment_type_id = self.appt_tech_call
        cfg.invalidate_recordset(['call_pool_shared_stages'])
        self.assertFalse(
            cfg.call_pool_shared_stages,
            "A type nobody else books needs no warning at all.")


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

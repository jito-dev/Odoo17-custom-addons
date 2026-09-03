# -*- coding: utf-8 -*-
"""Configuring a Call Stage against somebody else's appointment type.

v17.0.26.0.0 made a recruiter able to hand a call to a colleague. Half of that
was a record rule — stock limits Appointment Users to types they created or
staff, so a recruiter found only their own in the dropdown — and half was the
stage growing the type's bookable staff to fit whoever was picked.

v17.0.28.0.0 retired the second half along with the Interviewer field: the
type's own staff is the only answer to who runs a call, so there is no pool to
grow and nothing that can drift out of step with it. The record rule stays, and
matters more than ever — pointing a stage at a colleague's type is now the
whole configuration.

What is left here is that rule, and the warnings that depend on who is on the
chosen type.
"""
from unittest.mock import patch

from odoo.tests.common import tagged

from .common import CallStageTestCommon


@tagged('post_install', '-at_install')
class TestAppointmentTypeVisibility(CallStageTestCommon):
    """The other half: a recruiter must SEE colleagues' appointment types.

    Stock `appointment.appointment_type_rule_user` limits an Appointment User
    to types they created or are staff on. Record rules attached to groups are
    OR-ed, so this module ships a read-only rule for recruiters instead of
    touching the stock one.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.stranger = cls.env['res.users'].create({
            'name': 'Somebody Else', 'login': 'cs_stranger',
            'email': 'cs_stranger@example.com',
        })
        groups = cls.env.ref('hr_recruitment.group_hr_recruitment_user')
        appt_group = cls.env.ref(
            'appointment.group_appointment_user', raise_if_not_found=False)
        if appt_group:
            groups |= appt_group
        cls.recruiter = cls.env['res.users'].create({
            'name': 'Pool Recruiter', 'login': 'cs_pool_recruiter',
            'email': 'cs_pool_recruiter@example.com',
            'groups_id': [(6, 0, groups.ids)],
        })
        # A type the recruiter neither created nor staffs.
        cls.appt_hr_call.staff_user_ids = [(6, 0, [cls.stranger.id])]

    def test_recruiter_sees_a_colleagues_appointment_type(self):
        found = self.AppointmentType.with_user(self.recruiter).search([
            ('id', '=', self.appt_hr_call.id),
        ])
        self.assertEqual(
            found, self.appt_hr_call,
            "The Appointment type dropdown showed a recruiter only their own "
            "types; the read-only recruitment rule must lift that.")

    def test_recruiter_still_cannot_write_on_it(self):
        with self.assertRaises(Exception):
            self.appt_hr_call.with_user(self.recruiter).write(
                {'name': 'Renamed by a recruiter'})

    def test_recruiter_can_configure_a_stage_on_it(self):
        """Read-only on the type is enough to build the whole stage on it."""
        cfg = self._get_config(self.job_designer, self.stage_call).with_user(
            self.recruiter)
        cfg.write({
            'is_call_stage': True,
            'booking_appointment_type_id': self.appt_hr_call.id,
        })
        self.assertEqual(
            cfg.booking_appointment_type_id, self.appt_hr_call)
        self.assertEqual(
            cfg.call_staff_pool_ids, self.stranger,
            "Who runs the call is read off the colleague's type — through "
            "sudo, so a record rule cannot empty the display.")


@tagged('post_install', '-at_install')
class TestUnsyncedCalendarWarning(CallStageTestCommon):
    """v17.0.26.1.0 — an unsynced calendar makes every slot look free.

    Slot availability is read from `calendar.event` rows in Odoo only
    (`appointment.type._slot_availability_prepare_users_values_meetings`); the
    engine never calls Google. So an interviewer who never connected their
    calendar has no busy time here and the candidate can book straight over a
    real meeting. The warning used to fire only for google_meet types, which
    missed exactly that.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.interviewer = cls.env['res.users'].create({
            'name': 'Unsynced Person', 'login': 'cs_unsynced',
            'email': 'cs_unsynced@example.com',
        })
        cls.appt_hr_call.staff_user_ids = [(6, 0, [cls.interviewer.id])]

    def _configured(self):
        cfg = self._get_config(self.job_designer, self.stage_call)
        cfg.write({
            'is_call_stage': True,
            'booking_appointment_type_id': self.appt_hr_call.id,
        })
        return cfg

    def test_warning_fires_without_a_google_meet_type(self):
        cfg = self._configured()
        # Saving a Call Stage config makes the Google Meet bridge force its
        # booking type to `google_meet` — and that bridge auto-installs
        # wherever both parents are present, so on a real database this
        # assertion was unreachable and the test failed for ever. Put the
        # source back to the non-Meet one the test is actually about, the way
        # the sibling test below pins the opposite case explicitly.
        self.appt_hr_call.event_videocall_source = 'discuss'
        with patch.object(type(cfg), '_call_user_calendar_synced',
                          lambda self, user: False):
            cfg.invalidate_recordset(['call_warn_staff_unsynced',
                                      'call_warn_unsynced_names',
                                      'call_warn_unsynced_breaks_meet'])
            self.assertTrue(
                cfg.call_warn_staff_unsynced,
                "The free-looking-slots risk exists whatever the videocall "
                "source is.")
            self.assertEqual(
                cfg.call_warn_unsynced_names, self.interviewer.name)
            self.assertFalse(
                cfg.call_warn_unsynced_breaks_meet,
                "The join-link clause belongs to google_meet types only.")

    def test_meet_clause_only_on_a_google_meet_type(self):
        selection = self.AppointmentType._fields['event_videocall_source'].get_values(self.env)
        if 'google_meet' not in selection:
            self.skipTest('appointment_google_calendar is not installed')
        cfg = self._configured()
        self.appt_hr_call.event_videocall_source = 'google_meet'
        with patch.object(type(cfg), '_call_user_calendar_synced',
                          lambda self, user: False):
            cfg.invalidate_recordset(['call_warn_staff_unsynced',
                                      'call_warn_unsynced_breaks_meet'])
            self.assertTrue(cfg.call_warn_unsynced_breaks_meet)

    def test_no_warning_when_everyone_is_synced(self):
        cfg = self._configured()
        with patch.object(type(cfg), '_call_user_calendar_synced',
                          lambda self, user: True):
            cfg.invalidate_recordset(['call_warn_staff_unsynced'])
            self.assertFalse(cfg.call_warn_staff_unsynced)

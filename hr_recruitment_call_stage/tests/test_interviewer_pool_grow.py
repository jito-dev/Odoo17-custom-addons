# -*- coding: utf-8 -*-
"""v17.0.26.0.0 — a recruiter can hand the call to a colleague.

Before this version the Interviewer dropdown was bounded by
``appointment.type.staff_user_ids``, and that pool defaults to the single user
who created the type. A recruiter therefore only ever found *themselves* there
and could not assign an interview to anyone else.

The fix has two halves, both covered here:

* the appointment type itself must be *visible* to a recruiter (stock record
  rule limits Appointment Users to their own types);
* picking anyone internal must *grow* the type's bookable staff — union only,
  never an unlink — because ``appointment.invite`` can only ever narrow that
  pool.
"""
from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.tests.common import tagged

from .common import CallStageTestCommon


@tagged('post_install', '-at_install')
class TestInterviewerPoolGrowth(CallStageTestCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.owner = cls.env['res.users'].create({
            'name': 'Pool Owner', 'login': 'cs_pool_owner',
            'email': 'cs_owner@example.com',
        })
        cls.colleague = cls.env['res.users'].create({
            'name': 'CTO Colleague', 'login': 'cs_cto',
            'email': 'cs_cto@example.com',
        })
        cls.second_colleague = cls.env['res.users'].create({
            'name': 'Team Lead', 'login': 'cs_lead',
            'email': 'cs_lead@example.com',
        })
        # The starting point that caused the complaint: a type whose bookable
        # staff is exactly the person who made it.
        cls.appt_hr_call.staff_user_ids = [(6, 0, [cls.owner.id])]

    def _call_config(self, job=None, appt=None):
        cfg = self._get_config(job or self.job_designer, self.stage_call)
        cfg.write({
            'is_call_stage': True,
            'booking_appointment_type_id': (appt or self.appt_hr_call).id,
        })
        return cfg

    # ------------------------------------------------------------------
    # Growing the pool
    # ------------------------------------------------------------------
    def test_picking_someone_outside_the_pool_adds_them(self):
        cfg = self._call_config()
        cfg.call_staff_user_ids = [(6, 0, [self.colleague.id])]
        self.assertIn(
            self.colleague, self.appt_hr_call.staff_user_ids,
            "Picking an interviewer must make them bookable on the type — "
            "appointment.invite can only narrow that pool, never extend it.")

    def test_growing_the_pool_never_removes_anyone(self):
        cfg = self._call_config()
        cfg.call_staff_user_ids = [(6, 0, [self.colleague.id])]
        self.assertIn(
            self.owner, self.appt_hr_call.staff_user_ids,
            "The union must keep whoever the appointment type already had.")

    def test_deselecting_keeps_the_user_bookable(self):
        cfg = self._call_config()
        cfg.call_staff_user_ids = [(6, 0, [self.colleague.id])]
        cfg.call_staff_user_ids = [(5, 0, 0)]
        self.assertIn(
            self.colleague, self.appt_hr_call.staff_user_ids,
            "Dropping an interviewer from one stage must not take their "
            "calendar away from every other stage using the type.")

    def test_switching_type_carries_the_interviewer_over(self):
        cfg = self._call_config()
        cfg.call_staff_user_ids = [(6, 0, [self.colleague.id])]
        cfg.booking_appointment_type_id = self.appt_tech_call
        self.assertEqual(
            cfg.call_staff_user_ids, self.colleague,
            "The selection must survive a type change — the new type's pool "
            "grows to fit it instead of the choice being silently dropped.")
        self.assertIn(self.colleague, self.appt_tech_call.staff_user_ids)

    def test_creating_a_configured_row_grows_the_pool(self):
        """The ORM create path must behave like the form."""
        stage = self.Stage.create({
            'name': 'Second call CS',
            'sequence': 35,
            'job_ids': [(6, 0, [self.job_engineer.id])],
        })
        cfg = self._get_config(self.job_engineer, stage)
        cfg.unlink()
        cfg = self.Config.create({
            'job_id': self.job_engineer.id,
            'stage_id': stage.id,
            'is_call_stage': True,
            'booking_appointment_type_id': self.appt_hr_call.id,
            'call_staff_user_ids': [(6, 0, [self.second_colleague.id])],
        })
        self.assertTrue(cfg)
        self.assertIn(self.second_colleague, self.appt_hr_call.staff_user_ids)

    # ------------------------------------------------------------------
    # What growing cannot fix
    # ------------------------------------------------------------------
    def test_resource_based_type_refuses_an_interviewer(self):
        appt_resource = self.AppointmentType.create({
            'name': 'Resource Room CS',
            'appointment_duration': 0.5,
            'appointment_tz': 'UTC',
            'schedule_based_on': 'resources',
        })
        cfg = self._call_config()
        with self.assertRaises(ValidationError):
            cfg.write({
                'booking_appointment_type_id': appt_resource.id,
                'call_staff_user_ids': [(6, 0, [self.colleague.id])],
            })

    def test_switching_to_a_resource_type_prunes_instead_of_raising(self):
        """A selection the caller did not touch must not blow up their write."""
        appt_resource = self.AppointmentType.create({
            'name': 'Resource Room CS 2',
            'appointment_duration': 0.5,
            'appointment_tz': 'UTC',
            'schedule_based_on': 'resources',
        })
        cfg = self._call_config()
        cfg.call_staff_user_ids = [(6, 0, [self.colleague.id])]
        cfg.booking_appointment_type_id = appt_resource
        self.assertFalse(
            cfg.call_staff_user_ids,
            "Switching to a type that schedules resources must clear the "
            "interviewer rather than raise about an untouched field.")

    def test_anytime_type_refuses_a_second_person(self):
        appt_anytime = self.AppointmentType.create({
            'name': 'Anytime CS',
            'appointment_duration': 0.5,
            'appointment_tz': 'UTC',
            'category': 'anytime',
            'staff_user_ids': [(6, 0, [self.owner.id])],
        })
        cfg = self._call_config()
        with self.assertRaises(ValidationError):
            cfg.write({
                'booking_appointment_type_id': appt_anytime.id,
                'call_staff_user_ids': [(6, 0, [self.colleague.id])],
            })

    # ------------------------------------------------------------------
    # The pre-save banner
    # ------------------------------------------------------------------
    def test_banner_names_who_will_be_added(self):
        cfg = self._call_config()
        form_cfg = cfg.new({
            'job_id': cfg.job_id.id,
            'stage_id': cfg.stage_id.id,
            'is_call_stage': True,
            'booking_appointment_type_id': self.appt_hr_call.id,
            'call_staff_user_ids': [(6, 0, [self.colleague.id])],
        })
        self.assertEqual(form_cfg.call_pool_add_names, self.colleague.name)

    def test_banner_is_silent_when_nothing_changes(self):
        cfg = self._call_config()
        cfg.call_staff_user_ids = [(6, 0, [self.owner.id])]
        self.assertFalse(
            cfg.call_pool_add_names,
            "Picking someone already bookable must not warn about anything.")

    def test_banner_lists_sibling_stages_that_book_the_whole_pool(self):
        sibling = self._call_config(job=self.job_engineer)
        sibling.call_staff_user_ids = [(5, 0, 0)]
        form_cfg = self.Config.new({
            'job_id': self.job_designer.id,
            'stage_id': self.stage_call.id,
            'is_call_stage': True,
            'booking_appointment_type_id': self.appt_hr_call.id,
            'call_staff_user_ids': [(6, 0, [self.colleague.id])],
        })
        self.assertIn(
            self.job_engineer.display_name,
            form_cfg.call_pool_shared_stages or '',
            "A sibling stage that books the whole pool is affected by the "
            "growth and must be named before the recruiter saves.")

    # ------------------------------------------------------------------
    # The invite still pins exactly the selection
    # ------------------------------------------------------------------
    def test_invite_values_pin_only_the_selection(self):
        cfg = self._call_config()
        cfg.call_staff_user_ids = [(6, 0, [self.colleague.id])]
        values = cfg._call_invite_values()
        self.assertEqual(values.get('resources_choice'), 'specific_resources')
        self.assertEqual(
            values['staff_user_ids'][0][2], self.colleague.ids,
            "Growing the pool must not widen who this stage actually books.")


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
        cfg = self._get_config(self.job_designer, self.stage_call).with_user(
            self.recruiter)
        cfg.write({
            'is_call_stage': True,
            'booking_appointment_type_id': self.appt_hr_call.id,
            'call_staff_user_ids': [(6, 0, [self.recruiter.id])],
        })
        self.assertIn(
            self.recruiter, self.appt_hr_call.staff_user_ids,
            "Configuring the stage must grow the pool through sudo, without "
            "requiring write access on a colleague's appointment type.")


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
            'call_staff_user_ids': [(6, 0, [self.interviewer.id])],
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

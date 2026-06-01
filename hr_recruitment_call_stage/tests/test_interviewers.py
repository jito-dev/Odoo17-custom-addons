# -*- coding: utf-8 -*-
"""v17.0.16.0.0 — additional interviewers on a Call Stage.

Covers:

A. Seeding ``hr.applicant.call_interviewer_user_ids`` from the Call Stage
   default on stage entry — and the guards (exact-stage match, empty-only,
   never re-stomp a deliberate clear).
B. Attendee injection: interviewers' partners land on the booked
   ``calendar.event.partner_ids`` (idempotently).
C. The not-staff invariant: interviewers never leak into
   ``appointment.type.staff_user_ids`` (must not gate availability).
D. The public avatar route's access gate.
"""
from datetime import datetime, timedelta

from odoo.tests import tagged

from .common import CallStageTestCommon


@tagged('post_install', '-at_install')
class TestInterviewers(CallStageTestCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Users = cls.env['res.users']
        cls.ceo = Users.create({
            'name': 'Cleo CEO CS',
            'login': 'cleo_ceo_cs@example.com',
            'email': 'cleo_ceo_cs@example.com',
        })
        cls.cto = Users.create({
            'name': 'Theo CTO CS',
            'login': 'theo_cto_cs@example.com',
            'email': 'theo_cto_cs@example.com',
        })
        cls.outsider = Users.create({
            'name': 'Ned Nobody CS',
            'login': 'ned_nobody_cs@example.com',
            'email': 'ned_nobody_cs@example.com',
        })

    def _enable(self, job, appt_type, interviewers=None):
        cfg = self._get_config(job, self.stage_call)
        vals = {
            'is_call_stage': True,
            'booking_appointment_type_id': appt_type.id,
        }
        if interviewers is not None:
            vals['interviewer_user_ids'] = [(6, 0, interviewers.ids)]
        cfg.write(vals)
        return cfg

    def _create_event(self, applicant, appt_type, invite):
        start = datetime.now() + timedelta(days=1)
        return self.CalendarEvent.create({
            'name': 'STOCK PLACEHOLDER — overridden',
            'start': start,
            'stop': start + timedelta(minutes=30),
            'appointment_type_id': appt_type.id,
            'appointment_invite_id': invite.id,
            'partner_ids': (
                [(6, 0, applicant.partner_id.ids)]
                if applicant.partner_id else False),
        })

    # ---- A. Seeding -------------------------------------------------
    def test_seed_on_stage_transition(self):
        # Born on a non-call stage, then dragged onto the Call Stage.
        self._enable(self.job_designer, self.appt_hr_call, self.ceo)
        pre_stage = self.Stage.create({
            'name': 'New CS', 'sequence': 5,
            'job_ids': [(6, 0, [self.job_designer.id])]})
        applicant = self._make_applicant(
            'Seed Anna CS', self.job_designer, pre_stage)
        self.assertFalse(applicant.call_interviewer_user_ids,
            "an applicant on a non-call stage must not be seeded")
        applicant.stage_id = self.stage_call.id
        self.assertEqual(applicant.call_interviewer_user_ids, self.ceo,
            "moving onto the Call Stage must seed the default interviewer")

    def test_seed_on_create_when_born_on_call_stage(self):
        # Created directly on the Call Stage (e.g. it is the job's default
        # stage, or an import lands the candidate there) — the write-transition
        # hook never fires, so create-seeding must cover it.
        self._enable(self.job_designer, self.appt_hr_call, self.ceo)
        applicant = self._make_applicant(
            'Born Ivy CS', self.job_designer, self.stage_call)
        self.assertEqual(applicant.call_interviewer_user_ids, self.ceo,
            "an applicant born on the Call Stage is seeded at create time")

    def test_seed_only_when_empty_preserves_recruiter_curation(self):
        self._enable(self.job_designer, self.appt_hr_call, self.ceo)
        applicant = self._make_applicant('Seed Bob CS', self.job_designer)
        # Recruiter pre-curates BEFORE the move.
        applicant.call_interviewer_user_ids = [(6, 0, self.cto.ids)]
        applicant.stage_id = self.stage_call.id
        self.assertEqual(applicant.call_interviewer_user_ids, self.cto,
            "a pre-set list must NOT be stomped by the stage default")

    def test_deliberate_clear_not_reseeded(self):
        self._enable(self.job_designer, self.appt_hr_call, self.ceo)
        applicant = self._make_applicant('Seed Cara CS', self.job_designer)
        applicant.stage_id = self.stage_call.id
        self.assertEqual(applicant.call_interviewer_user_ids, self.ceo)
        # Recruiter deliberately clears, then some other field write happens
        # that also touches stage_id (re-entry). Seed must not re-add.
        applicant.call_interviewer_user_ids = [(5, 0, 0)]
        applicant.write({'stage_id': self.stage_call.id})
        self.assertFalse(applicant.call_interviewer_user_ids,
            "a deliberate clear must survive a same-stage re-write")

    def test_no_seed_on_non_call_stage(self):
        # Stage default exists, but the applicant lands on a different stage.
        self._enable(self.job_designer, self.appt_hr_call, self.ceo)
        other_stage = self.Stage.create({
            'name': 'Screening CS', 'sequence': 10,
            'job_ids': [(6, 0, [self.job_designer.id])]})
        applicant = self._make_applicant('Seed Dan CS', self.job_designer)
        applicant.stage_id = other_stage.id
        self.assertFalse(applicant.call_interviewer_user_ids,
            "only the exact Call Stage entry seeds — not any stage move")

    def test_backstop_seed_on_generate_link(self):
        # Simulate an applicant already on the Call Stage before the feature
        # (no write hook fired) by clearing after the move, then generating
        # a link with an empty list while the default is set.
        cfg = self._enable(self.job_designer, self.appt_hr_call, self.ceo)
        applicant = self._make_applicant('Seed Eve CS', self.job_designer)
        applicant.stage_id = self.stage_call.id
        applicant.call_interviewer_user_ids = [(5, 0, 0)]
        # Add a fresh default and confirm the backstop picks it up on link gen.
        cfg.interviewer_user_ids = [(6, 0, self.cto.ids)]
        applicant.action_generate_booking_link()
        self.assertEqual(applicant.call_interviewer_user_ids, self.cto,
            "generate-link backstop must seed when the list is empty")

    # ---- B. Attendee injection -------------------------------------
    def test_interviewers_added_as_attendees(self):
        self._enable(self.job_designer, self.appt_hr_call,
                     self.ceo | self.cto)
        applicant = self._make_applicant('Att Frank CS', self.job_designer)
        applicant.stage_id = self.stage_call.id
        invite = applicant._get_or_create_booking_invite(self.appt_hr_call)
        event = self._create_event(applicant, self.appt_hr_call, invite)
        self.assertIn(self.ceo.partner_id, event.partner_ids,
            "the CEO must be added as an attendee of the booked call")
        self.assertIn(self.cto.partner_id, event.partner_ids,
            "the CTO must be added as an attendee of the booked call")
        self.assertIn(applicant.partner_id, event.partner_ids,
            "the candidate must remain an attendee")

    def test_no_interviewers_no_extra_attendees(self):
        self._enable(self.job_designer, self.appt_hr_call)
        applicant = self._make_applicant('Att Gina CS', self.job_designer)
        applicant.stage_id = self.stage_call.id
        invite = applicant._get_or_create_booking_invite(self.appt_hr_call)
        event = self._create_event(applicant, self.appt_hr_call, invite)
        self.assertEqual(event.partner_ids, applicant.partner_id,
            "with no interviewers only the candidate is an attendee")

    # ---- E. Config delta-propagation -------------------------------
    def test_config_removal_propagates_to_applicant_and_event(self):
        cfg = self._enable(self.job_designer, self.appt_hr_call,
                           self.ceo | self.cto)
        applicant = self._make_applicant('Prop Pat CS', self.job_designer)
        applicant.stage_id = self.stage_call.id  # seeds ceo | cto
        self.assertEqual(applicant.call_interviewer_user_ids,
                         self.ceo | self.cto)
        invite = applicant._get_or_create_booking_invite(self.appt_hr_call)
        event = self._create_event(applicant, self.appt_hr_call, invite)
        self.assertIn(self.ceo.partner_id, event.partner_ids)
        self.assertIn(self.cto.partner_id, event.partner_ids)
        # Drop the CEO from the Call Stage default.
        cfg.interviewer_user_ids = [(3, self.ceo.id)]
        self.assertEqual(applicant.call_interviewer_user_ids, self.cto,
            "removing an interviewer in the config must drop it from the "
            "applicant (CTO retained via delta)")
        self.assertNotIn(self.ceo.partner_id, event.partner_ids,
            "the dropped interviewer must leave the future event's attendees")
        self.assertIn(self.cto.partner_id, event.partner_ids,
            "the retained interviewer stays on the event")
        self.assertIn(applicant.partner_id, event.partner_ids,
            "the candidate is never removed by an interviewer delta")

    def test_config_addition_propagates_to_applicant_and_event(self):
        cfg = self._enable(self.job_designer, self.appt_hr_call, self.ceo)
        applicant = self._make_applicant('Prop Quinn CS', self.job_designer)
        applicant.stage_id = self.stage_call.id
        invite = applicant._get_or_create_booking_invite(self.appt_hr_call)
        event = self._create_event(applicant, self.appt_hr_call, invite)
        self.assertNotIn(self.cto.partner_id, event.partner_ids)
        cfg.interviewer_user_ids = [(4, self.cto.id)]
        self.assertIn(self.cto, applicant.call_interviewer_user_ids,
            "adding an interviewer in the config must reach the applicant")
        self.assertIn(self.cto.partner_id, event.partner_ids,
            "the added interviewer must join the future event's attendees")

    def test_config_change_preserves_per_candidate_extra(self):
        cfg = self._enable(self.job_designer, self.appt_hr_call, self.ceo)
        applicant = self._make_applicant('Prop Rae CS', self.job_designer)
        applicant.stage_id = self.stage_call.id  # seeds ceo
        # Recruiter adds a per-candidate extra by hand.
        applicant.call_interviewer_user_ids = [(4, self.cto.id)]
        # Config drops the CEO entirely.
        cfg.interviewer_user_ids = [(3, self.ceo.id)]
        self.assertEqual(applicant.call_interviewer_user_ids, self.cto,
            "delta propagation removes only the changed user — the hand-added "
            "per-candidate interviewer must survive")

    # ---- F. Card-edit reconciles the booked event ------------------
    def test_card_removal_reconciles_future_event(self):
        self._enable(self.job_designer, self.appt_hr_call, self.ceo | self.cto)
        applicant = self._make_applicant('Card Sam CS', self.job_designer)
        applicant.stage_id = self.stage_call.id
        invite = applicant._get_or_create_booking_invite(self.appt_hr_call)
        event = self._create_event(applicant, self.appt_hr_call, invite)
        self.assertIn(self.ceo.partner_id, event.partner_ids)
        applicant.call_interviewer_user_ids = [(3, self.ceo.id)]
        self.assertNotIn(self.ceo.partner_id, event.partner_ids,
            "editing the applicant card must reconcile the booked event")
        self.assertIn(self.cto.partner_id, event.partner_ids)
        self.assertIn(applicant.partner_id, event.partner_ids)

    def test_card_removal_leaves_past_event_intact(self):
        self._enable(self.job_designer, self.appt_hr_call, self.ceo)
        applicant = self._make_applicant('Card Tom CS', self.job_designer)
        applicant.stage_id = self.stage_call.id
        invite = applicant._get_or_create_booking_invite(self.appt_hr_call)
        # A call that already happened — its attendee history must not change.
        past = datetime.now() - timedelta(days=2)
        event = self.CalendarEvent.create({
            'name': 'Past call', 'start': past,
            'stop': past + timedelta(minutes=30),
            'appointment_type_id': self.appt_hr_call.id,
            'appointment_invite_id': invite.id,
            'partner_ids': [(6, 0, (
                applicant.partner_id | self.ceo.partner_id).ids)],
        })
        applicant.call_interviewer_user_ids = [(3, self.ceo.id)]
        self.assertIn(self.ceo.partner_id, event.partner_ids,
            "a past call's attendees must be left untouched")

    # ---- C. Not-staff invariant ------------------------------------
    def test_interviewers_never_gate_availability(self):
        self._enable(self.job_designer, self.appt_hr_call, self.ceo)
        self.appt_hr_call.invalidate_recordset(['staff_user_ids'])
        self.assertNotIn(self.ceo, self.appt_hr_call.staff_user_ids,
            "an interviewer must NEVER be pushed into staff_user_ids")

    # ---- D. Avatar route access gate -------------------------------
    def test_avatar_gate_predicate(self):
        # Mirrors the exact gate used by call_stage_interviewer_avatar: a
        # user is servable iff they are configured as an interviewer somewhere.
        self._enable(self.job_designer, self.appt_hr_call, self.ceo)
        applicant = self._make_applicant('Gate Hank CS', self.job_designer)
        applicant.stage_id = self.stage_call.id  # seeds ceo onto the applicant

        def is_interviewer(user):
            return bool(
                self.env['hr.job.stage.config'].sudo().search_count(
                    [('interviewer_user_ids', 'in', user.id)])
                or self.env['hr.applicant'].sudo().search_count(
                    [('call_interviewer_user_ids', 'in', user.id)]))

        self.assertTrue(is_interviewer(self.ceo),
            "a configured interviewer must pass the avatar gate")
        self.assertFalse(is_interviewer(self.outsider),
            "an unrelated user must NOT have their avatar served publicly")

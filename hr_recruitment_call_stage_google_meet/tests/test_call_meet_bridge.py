# -*- coding: utf-8 -*-
from datetime import datetime, timedelta

from odoo.tests import tagged

from odoo.addons.hr_recruitment_call_stage.tests.common import CallStageTestCommon

MEET_URL = 'https://meet.google.com/abc-defg-hij'


@tagged('post_install', '-at_install')
class TestCallMeetBridge(CallStageTestCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Drive the HR call appointment type through the native Google Meet
        # source (Odoo's Google Calendar sync attaches the Meet conference).
        cls.appt_hr_call.event_videocall_source = 'google_meet'

    # ---- helpers -----------------------------------------------------
    def _enable(self, job, appt_type):
        cfg = self._get_config(job, self.stage_call)
        cfg.write({
            'is_call_stage': True,
            'booking_appointment_type_id': appt_type.id,
        })
        return cfg

    def _booked_applicant(self, name, job, appt_type):
        applicant = self._make_applicant(name, job)
        applicant.stage_id = self.stage_call.id
        invite = applicant._get_or_create_booking_invite(appt_type)
        return applicant, invite

    def _create_event(self, applicant, appt_type, invite, location=MEET_URL, **kw):
        start = datetime.now() + timedelta(days=1)
        vals = {
            'name': 'placeholder',
            'start': start,
            'stop': start + timedelta(minutes=30),
            'appointment_type_id': appt_type.id,
            'appointment_invite_id': invite.id,
            'videocall_location': location,
            'partner_ids': [(6, 0, applicant.partner_id.ids)] if applicant.partner_id else False,
        }
        vals.update(kw)
        return self.CalendarEvent.create(vals)

    # ---- F0: single join link ---------------------------------------
    def test_f0_redirection_equals_location_for_meet(self):
        event = self.CalendarEvent.create({
            'name': 'Meet event',
            'start': datetime.now(),
            'stop': datetime.now() + timedelta(minutes=30),
            'videocall_location': MEET_URL,
        })
        self.assertEqual(event.videocall_source, 'google_meet_rest')
        self.assertEqual(
            event.videocall_redirection, event.videocall_location,
            "Join button (redirection) and body link (location) must be the "
            "same URL for a Google Meet event")

    def test_f0_non_meet_event_untouched(self):
        event = self.CalendarEvent.create({
            'name': 'Discuss event',
            'start': datetime.now(),
            'stop': datetime.now() + timedelta(minutes=30),
        })
        # Default discuss event: redirection points at the Odoo route, not
        # equal to a meet.google.com URL — our override must not touch it.
        self.assertNotEqual(event.videocall_source, 'google_meet_rest')

    # ---- Auto-enable Google Meet source on Call Stage config ---------
    def test_config_forces_google_meet_source(self):
        # A booking type left on the default 'discuss' source must be switched
        # to the native Google Meet source the moment its stage is configured
        # as a Call Stage, so booked calls get a Meet link via Google sync.
        self.appt_hr_call.event_videocall_source = 'discuss'
        self._enable(self.job_designer, self.appt_hr_call)
        self.assertEqual(
            self.appt_hr_call.event_videocall_source, 'google_meet',
            "Enabling a Call Stage must force its booking type to Google Meet")

    def test_config_non_call_stage_leaves_source(self):
        # Touching a config that is NOT a call stage must not rewrite the
        # appointment type's videocall source.
        self.appt_hr_call.event_videocall_source = 'discuss'
        cfg = self._get_config(self.job_designer, self.stage_call)
        cfg.write({'is_call_stage': False,
                   'booking_appointment_type_id': self.appt_hr_call.id})
        self.assertEqual(self.appt_hr_call.event_videocall_source, 'discuss',
                         "Non call-stage config must leave the source alone")

    # ---- F2: cockpit meet_url ----------------------------------------
    def test_f2_meet_url_reads_booked_event(self):
        self._enable(self.job_designer, self.appt_hr_call)
        applicant, invite = self._booked_applicant(
            'Cockpit CS', self.job_designer, self.appt_hr_call)
        self.assertFalse(applicant.meet_url)
        self._create_event(applicant, self.appt_hr_call, invite)
        applicant.invalidate_recordset(['meet_url'])
        self.assertEqual(applicant.meet_url, MEET_URL)

    # ---- F3 / F4: cancel ---------------------------------------------
    def test_f3_cancel_sets_state_but_raises_no_todo(self):
        # v17.0.2.0.0 — the state and the chatter note are immediate, the
        # to-do is not. At this instant a reschedule and a walk-out are the
        # same database change, so there is nothing to decide yet.
        self._enable(self.job_designer, self.appt_hr_call)
        applicant, invite = self._booked_applicant(
            'Cancel CS', self.job_designer, self.appt_hr_call)
        event = self._create_event(applicant, self.appt_hr_call, invite)
        applicant.invalidate_recordset(['call_status'])
        self.assertEqual(applicant.call_status, 'booked')
        before_activities = len(applicant.activity_ids)
        event.action_archive()
        applicant.invalidate_recordset(
            ['call_cancelled', 'call_status', 'activity_ids'])
        self.assertTrue(applicant.call_cancelled)
        self.assertEqual(applicant.call_status, 'cancelled')
        self.assertTrue(applicant.call_cancel_at,
                        "A cancellation must be queued for a verdict")
        self.assertEqual(
            len(applicant.activity_ids), before_activities,
            "Cancelling must NOT raise a to-do before the grace window: six "
            "of the nine ever raised in production were reschedules")
        self.assertTrue(
            any('Waiting to see' in (m.body or '')
                for m in applicant.message_ids),
            "The cancellation must still be recorded in chatter immediately")

    def test_f3_attended_wins_over_cancelled(self):
        self._enable(self.job_designer, self.appt_hr_call)
        applicant, invite = self._booked_applicant(
            'Won CS', self.job_designer, self.appt_hr_call)
        event = self._create_event(applicant, self.appt_hr_call, invite)
        applicant.call_cancelled = True
        # v17.0.24.13.0 — outcome lives on the booked call event now.
        event.call_outcome = 'attended'
        applicant.invalidate_recordset(['call_status', 'call_outcome'])
        self.assertEqual(applicant.call_status, 'attended',
                         "Recruiter outcome must win over cancelled flag")

    # ---- F3 / F4: reschedule -----------------------------------------
    def test_f3_reschedule_in_place(self):
        self._enable(self.job_designer, self.appt_hr_call)
        applicant, invite = self._booked_applicant(
            'Move CS', self.job_designer, self.appt_hr_call)
        event = self._create_event(applicant, self.appt_hr_call, invite)
        event.start = event.start + timedelta(hours=2)
        applicant.invalidate_recordset(['call_rescheduled', 'call_status', 'call_booked_start'])
        self.assertTrue(applicant.call_rescheduled)
        self.assertEqual(applicant.call_status, 'rescheduled')
        self.assertEqual(applicant.call_booked_start, event.start)

    def test_first_booking_stays_booked(self):
        """A clean first booking must read 'booked', never 'rescheduled'.

        Guards the regression where the reschedule flag was derived from the
        invite's event history: the per-applicant invite is reused across
        bookings, so any prior row on it wrongly flipped a fresh booking to
        'rescheduled'.
        """
        self._enable(self.job_designer, self.appt_hr_call)
        applicant, invite = self._booked_applicant(
            'Fresh CS', self.job_designer, self.appt_hr_call)
        self._create_event(applicant, self.appt_hr_call, invite)
        applicant.invalidate_recordset(['call_rescheduled', 'call_status'])
        self.assertFalse(applicant.call_rescheduled,
                         "A first booking must not set the reschedule flag")
        self.assertEqual(applicant.call_status, 'booked',
                         "A first booking must read 'booked', not 'rescheduled'")

    def test_lingering_event_on_invite_is_not_a_reschedule(self):
        """A second active booking on the same (reused) invite, with NO
        cancellation in between, must stay 'booked' — only a real
        cancel→rebook (tracked by ``call_cancelled``) is a reschedule."""
        self._enable(self.job_designer, self.appt_hr_call)
        applicant, invite = self._booked_applicant(
            'Lingering CS', self.job_designer, self.appt_hr_call)
        # A prior event lingers on the invite (e.g. a past slot or a Google
        # sync duplicate) but was never cancelled.
        self._create_event(applicant, self.appt_hr_call, invite)
        # The candidate books again — no cancellation happened in between.
        self._create_event(applicant, self.appt_hr_call, invite)
        applicant.invalidate_recordset(['call_rescheduled', 'call_status'])
        self.assertFalse(applicant.call_rescheduled,
                         "A lingering event must not fake a reschedule")
        self.assertEqual(applicant.call_status, 'booked')

    def test_multi_call_stage_first_booking_stays_booked(self):
        """A job with SEVERAL Call Stages: a plain first booking against any
        of them reads 'booked', never 'rescheduled'."""
        # Stage 1: the shared call stage, booking the HR call type.
        self._enable(self.job_designer, self.appt_hr_call)
        # Stage 2: a second Call Stage on the SAME job, different type.
        stage_call_2 = self.Stage.create({
            'name': 'Second Call CS',
            'sequence': 35,
            'job_ids': [(6, 0, [self.job_designer.id])],
        })
        cfg2 = self._get_config(self.job_designer, stage_call_2)
        self.assertTrue(cfg2, "Second call stage must have a config row")
        cfg2.write({
            'is_call_stage': True,
            'booking_appointment_type_id': self.appt_tech_call.id,
        })

        # Candidate A books against the first Call Stage's type.
        app_a = self._make_applicant('Multi A', self.job_designer)
        app_a.stage_id = self.stage_call.id
        invite_a = app_a._get_or_create_booking_invite(self.appt_hr_call)
        self._create_event(app_a, self.appt_hr_call, invite_a)
        app_a.invalidate_recordset(['call_rescheduled', 'call_status'])
        self.assertFalse(app_a.call_rescheduled)
        self.assertEqual(app_a.call_status, 'booked',
                         "Booking on call stage 1 must read 'booked'")

        # Candidate B books against the second Call Stage's type.
        app_b = self._make_applicant('Multi B', self.job_designer)
        app_b.stage_id = stage_call_2.id
        invite_b = app_b._get_or_create_booking_invite(self.appt_tech_call)
        self._create_event(app_b, self.appt_tech_call, invite_b)
        app_b.invalidate_recordset(['call_rescheduled', 'call_status'])
        self.assertFalse(app_b.call_rescheduled)
        self.assertEqual(app_b.call_status, 'booked',
                         "Booking on call stage 2 must read 'booked'")

    def test_f3_reschedule_cancel_then_rebook(self):
        self._enable(self.job_designer, self.appt_hr_call)
        applicant, invite = self._booked_applicant(
            'Rebook CS', self.job_designer, self.appt_hr_call)
        event1 = self._create_event(applicant, self.appt_hr_call, invite)
        event1.action_archive()
        applicant.invalidate_recordset(['call_cancelled'])
        self.assertTrue(applicant.call_cancelled)
        # Candidate picks a new slot — native flow creates a new event.
        self._create_event(applicant, self.appt_hr_call, invite)
        applicant.invalidate_recordset(['call_cancelled', 'call_rescheduled', 'call_status'])
        self.assertFalse(applicant.call_cancelled, "Rebook clears cancellation")
        self.assertTrue(applicant.call_rescheduled)
        self.assertEqual(applicant.call_status, 'rescheduled')

    # ---- Cancellation settling (v17.0.2.0.0) -------------------------
    #
    # The portal has no "reschedule" action: `Cancel/Reschedule` archives the
    # event and returns the candidate to the slot picker, so every reschedule
    # IS a cancellation followed by a booking. These tests pin the rule that
    # replaces the immediate alert — a to-do is raised for a state that has
    # held for the grace window, never for the event itself.

    def _settle(self, applicant, minutes_ago=60):
        """Age the pending cancellation and run the sweep."""
        applicant.sudo().call_cancel_at = (
            datetime.now() - timedelta(minutes=minutes_ago))
        self.env['hr.applicant']._cron_call_stage_confirm_cancellations()
        applicant.invalidate_recordset(
            ['activity_ids', 'call_cancel_at', 'call_cancel_activity_id',
             'call_cancelled', 'call_status'])

    def _cancel_todos(self, applicant):
        return applicant.activity_ids.filtered(
            lambda a: a.summary == 'Cancelled call — decide the next step')

    def test_reschedule_inside_window_never_raises_todo(self):
        # E1 — the common case, and the whole reason for the redesign.
        self._enable(self.job_designer, self.appt_hr_call)
        applicant, invite = self._booked_applicant(
            'Grace CS', self.job_designer, self.appt_hr_call)
        event = self._create_event(applicant, self.appt_hr_call, invite)
        event.action_archive()
        self._create_event(applicant, self.appt_hr_call, invite)
        self._settle(applicant)
        self.assertFalse(
            self._cancel_todos(applicant),
            "A candidate who rebooked must never generate a to-do")
        self.assertFalse(applicant.call_cancelled)
        self.assertEqual(applicant.call_status, 'rescheduled')

    def test_abandoned_booking_raises_one_titled_todo(self):
        # E3 of the plan: silence through the window is a real cancellation.
        self._enable(self.job_designer, self.appt_hr_call)
        applicant, invite = self._booked_applicant(
            'Gone CS', self.job_designer, self.appt_hr_call)
        event = self._create_event(applicant, self.appt_hr_call, invite)
        event.action_archive()
        self._settle(applicant)
        todos = self._cancel_todos(applicant)
        self.assertEqual(len(todos), 1, "Exactly one to-do for one walk-out")
        self.assertNotEqual(
            todos.summary, 'Fix Call Stage booking link',
            "The cancellation to-do must not borrow the booking-link title")
        self.assertEqual(applicant.call_cancel_activity_id, todos)
        self.assertFalse(applicant.call_cancel_at,
                         "A settled cancellation leaves the sweep's domain")

    def test_sweep_is_idempotent(self):
        # E13 — a second pass (a retried cron, a catch-up run) adds nothing.
        self._enable(self.job_designer, self.appt_hr_call)
        applicant, invite = self._booked_applicant(
            'Twice CS', self.job_designer, self.appt_hr_call)
        self._create_event(applicant, self.appt_hr_call, invite).action_archive()
        self._settle(applicant)
        self.env['hr.applicant']._cron_call_stage_confirm_cancellations()
        applicant.invalidate_recordset(['activity_ids'])
        self.assertEqual(len(self._cancel_todos(applicant)), 1)

    def test_late_rebooking_closes_the_todo(self):
        # E2 — the to-do was true when raised; closing beats deleting.
        self._enable(self.job_designer, self.appt_hr_call)
        applicant, invite = self._booked_applicant(
            'Late CS', self.job_designer, self.appt_hr_call)
        self._create_event(applicant, self.appt_hr_call, invite).action_archive()
        self._settle(applicant)
        self.assertTrue(self._cancel_todos(applicant))
        self._create_event(applicant, self.appt_hr_call, invite)
        applicant.invalidate_recordset(
            ['activity_ids', 'call_cancel_activity_id', 'call_cancelled'])
        self.assertFalse(self._cancel_todos(applicant),
                         "A late rebooking must retract the open to-do")
        self.assertFalse(applicant.call_cancel_activity_id)
        self.assertFalse(applicant.call_cancelled)

    def test_manually_closed_todo_is_not_reopened(self):
        # E3 — `ondelete='set null'` already cleared the link; rebooking must
        # not resurrect anything or crash on the dangling reference.
        self._enable(self.job_designer, self.appt_hr_call)
        applicant, invite = self._booked_applicant(
            'Manual CS', self.job_designer, self.appt_hr_call)
        self._create_event(applicant, self.appt_hr_call, invite).action_archive()
        self._settle(applicant)
        self._cancel_todos(applicant).action_feedback(feedback='handled')
        applicant.invalidate_recordset(
            ['activity_ids', 'call_cancel_activity_id'])
        self.assertFalse(applicant.call_cancel_activity_id)
        self._create_event(applicant, self.appt_hr_call, invite)
        applicant.invalidate_recordset(['activity_ids', 'call_cancelled'])
        self.assertFalse(self._cancel_todos(applicant))
        self.assertFalse(applicant.call_cancelled)

    def test_second_cancellation_does_not_duplicate_the_todo(self):
        # E5 — production handed one recruiter two to-dos for one candidate.
        self._enable(self.job_designer, self.appt_hr_call)
        applicant, invite = self._booked_applicant(
            'Double CS', self.job_designer, self.appt_hr_call)
        self._create_event(applicant, self.appt_hr_call, invite).action_archive()
        self._settle(applicant)
        second = self._create_event(applicant, self.appt_hr_call, invite)
        second.action_archive()
        self._settle(applicant)
        self.assertEqual(
            len(self._cancel_todos(applicant)), 1,
            "One open cancellation to-do per applicant, never a pile")

    def test_refused_applicant_gets_no_todo(self):
        # E9 — out of the funnel by a recruiter decision.
        self._enable(self.job_designer, self.appt_hr_call)
        applicant, invite = self._booked_applicant(
            'Refused CS', self.job_designer, self.appt_hr_call)
        self._create_event(applicant, self.appt_hr_call, invite).action_archive()
        applicant.refuse_reason_id = self.env[
            'hr.applicant.refuse.reason'].create({'name': 'Not a fit CS'}).id
        self._settle(applicant)
        self.assertFalse(self._cancel_todos(applicant))

    def test_past_slot_gets_no_todo(self):
        # E11 — tidying up a call that already happened is not a decision.
        self._enable(self.job_designer, self.appt_hr_call)
        applicant, invite = self._booked_applicant(
            'Past CS', self.job_designer, self.appt_hr_call)
        start = datetime.now() - timedelta(days=2)
        event = self._create_event(
            applicant, self.appt_hr_call, invite,
            start=start, stop=start + timedelta(minutes=30))
        event.action_archive()
        applicant.invalidate_recordset(['call_cancel_at', 'activity_ids'])
        self.assertFalse(applicant.call_cancel_at,
                         "A past slot must not even be queued for a verdict")
        self._settle(applicant)
        self.assertFalse(self._cancel_todos(applicant))

    def test_live_booking_clears_a_stale_cancellation(self):
        # E14 — an event un-archived by hand, or restored from Google.
        self._enable(self.job_designer, self.appt_hr_call)
        applicant, invite = self._booked_applicant(
            'Restored CS', self.job_designer, self.appt_hr_call)
        event = self._create_event(applicant, self.appt_hr_call, invite)
        event.action_archive()
        # Bring it back without going through the booking hook.
        event.with_context(call_stage_skip=True).write({'active': True})
        self._settle(applicant)
        self.assertFalse(self._cancel_todos(applicant))
        self.assertFalse(applicant.call_cancelled,
                         "A live booking means the applicant is not cancelled")

    def test_configuration_alerts_keep_their_title(self):
        # Anti-regression: the eight callers this helper was built for say
        # "a call-invite email was NOT sent, fix the configuration", and that
        # is exactly what their title must keep saying.
        applicant = self._make_applicant('Title CS', self.job_designer)
        activity = applicant._call_stage_alert_recruiter(reason='Something')
        self.assertEqual(activity.summary, 'Fix Call Stage booking link')

    def test_alert_owner_prefers_the_people_who_own_the_hiring(self):
        # E15 — the sweep runs as OdooBot and the Google sync as whichever
        # colleague's calendar carried the event; neither may inherit the to-do.
        Users = self.env['res.users']
        recruiter = Users.create({
            'name': 'Job Recruiter CS',
            'login': 'job.recruiter.cs@example.com',
        })
        owner = Users.create({
            'name': 'Applicant Owner CS',
            'login': 'applicant.owner.cs@example.com',
        })
        self.job_designer.user_id = recruiter.id
        applicant = self._make_applicant('Owner CS', self.job_designer)

        applicant.sudo().user_id = owner.id
        self.assertEqual(
            applicant._call_stage_alert_user(), owner,
            "The applicant's own recruiter always comes first")

        applicant.sudo().user_id = False
        self.assertEqual(
            applicant._call_stage_alert_user(), recruiter,
            "With no responsible recruiter, the vacancy's owner takes it")
        # The sweep runs as OdooBot, which ships inactive: a to-do assigned
        # to it is a to-do nobody will ever see.
        self.assertNotEqual(applicant._call_stage_alert_user(), self.env.user)

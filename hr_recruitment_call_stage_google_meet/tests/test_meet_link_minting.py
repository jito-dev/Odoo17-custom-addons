# -*- coding: utf-8 -*-
"""Does a booked call actually get a Google Meet link?

The module never mints one. Google does, during the Odoo→Google push, and only
if Odoo asks — so the chain has four links and every one of them can break
quietly:

1. the Call Stage's booking type is on the native ``google_meet`` source
   (forced by ``hr_job_stage_config._apply_call_stage_google_meet_source``);
2. the booked event asks for a conference — ``_google_values()`` puts
   ``conferenceData.createRequest`` in the payload
   (``appointment_google_calendar``), but only while the event has no
   ``google_id`` and no ``videocall_location`` yet;
3. the event is actually pushed, which needs a user with a Google token —
   ``_get_event_user()`` picks the organiser when they have one;
4. Google's answer carries ``hangoutLink`` and ``_get_post_sync_values`` writes
   it onto ``videocall_location``, where the cockpit reads it.

Link 2 and link 4 had no coverage at all, which is what let "the booking
succeeded but there is no way to join" stay silent. Nothing here talks to
Google: the payload is inspected before it would be sent, and the answer is
handed back as the stock service would (``google_service._do_request`` returns
``(status, body, ask_time)``, and the callback is given that tuple).
"""
from datetime import datetime, timedelta

from odoo.tests import tagged

from odoo.addons.hr_recruitment_call_stage.tests.common import CallStageTestCommon

MEET_URL = 'https://meet.google.com/xyz-abcd-efg'
GOOGLE_ID = 'googleeventid123'


def _google_answer(hangout=MEET_URL):
    """What the stock insert callback receives back from Google."""
    body = {'id': GOOGLE_ID}
    if hangout:
        body['hangoutLink'] = hangout
    return (200, body, None)


@tagged('post_install', '-at_install')
class TestMeetLinkMinting(CallStageTestCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.interviewer = cls.env['res.users'].create({
            'name': 'Meet Interviewer', 'login': 'cs_meet_interviewer',
            'email': 'cs_meet@example.com',
        })
        cls.appt_hr_call.staff_user_ids = [(6, 0, [cls.interviewer.id])]
        cls.cfg = cls._get_config(cls.job_designer, cls.stage_call)
        cls.cfg.write({
            'is_call_stage': True,
            'booking_appointment_type_id': cls.appt_hr_call.id,
        })

    def _booked_event(self, **kw):
        applicant = self._make_applicant(
            kw.pop('applicant_name', 'Meet Candidate'),
            self.job_designer, self.stage_call)
        invite = applicant._get_or_create_booking_invite(self.appt_hr_call)
        start = datetime.now() + timedelta(days=2)
        vals = {
            'name': 'Booked call',
            'start': start,
            'stop': start + timedelta(minutes=30),
            'appointment_type_id': self.appt_hr_call.id,
            'appointment_invite_id': invite.id,
            'user_id': self.interviewer.id,
            'partner_ids': [(6, 0, (applicant.partner_id | self.interviewer.partner_id).ids)],
        }
        vals.update(kw)
        return applicant, self.CalendarEvent.create(vals)

    # ---- link 1: the type is on the native Google Meet source ---------
    def test_a_stage_on_a_discuss_type_still_asks_for_a_meet(self):
        """Starts from the hostile state on purpose.

        `google_meet_integration` already DEFAULTS new appointment types to
        `google_meet`, so asserting the end state on a fresh type passes even
        with the bridge's forcing removed — it proves nothing. Setting the
        source back to `discuss` first is what makes this test about the
        guarantee: save a Call Stage on that type and it must come out asking
        Google for a conference anyway. Any other source and
        `appointment_google_calendar._google_values` STRIPS conferenceData, so
        the booking succeeds with nothing to join.
        """
        self.appt_hr_call.event_videocall_source = 'discuss'
        self.cfg.write({
            'is_call_stage': True,
            'booking_appointment_type_id': self.appt_hr_call.id,
        })
        self.assertEqual(
            self.appt_hr_call.event_videocall_source, 'google_meet',
            "Saving a Call Stage must put its booking type back on Google Meet")
        _applicant, event = self._booked_event(applicant_name='Rescued Source')
        self.assertIn('conferenceData', event._google_values())

    # ---- link 2: Odoo asks Google for a conference --------------------
    def test_booked_call_asks_google_for_a_conference(self):
        _applicant, event = self._booked_event()
        values = event._google_values()
        self.assertIn(
            'conferenceData', values,
            "Without this key in the payload Google creates a plain event and "
            "the candidate gets an invite with nothing to click.")
        self.assertIn('createRequest', values['conferenceData'])

    def test_no_conference_is_asked_for_on_another_source(self):
        self.appt_hr_call.event_videocall_source = 'discuss'
        _applicant, event = self._booked_event(applicant_name='Discuss Candidate')
        self.assertNotIn('conferenceData', event._google_values())

    def test_no_conference_is_asked_for_twice(self):
        """A link already on the event is never replaced by a second one."""
        _applicant, event = self._booked_event(
            applicant_name='Has Link Candidate', videocall_location=MEET_URL)
        self.assertNotIn('conferenceData', event._google_values())

    def test_no_conference_once_the_event_lives_in_google(self):
        """The ask only rides on the INSERT.

        Later pushes go through `_google_patch`, whose URL carries no
        `conferenceDataVersion=1` (google_calendar/utils/google_calendar.py) —
        so an event that reached Google without a conference can never gain one.
        Cancel-and-rebook is the only cure, and that is worth knowing.
        """
        _applicant, event = self._booked_event(
            applicant_name='Already Synced Candidate')
        event.with_context(dont_notify=True).write({'google_id': GOOGLE_ID})
        self.assertNotIn('conferenceData', event._google_values())

    # ---- link 3: somebody with a token has to do the pushing ----------
    def test_the_organiser_pushes_when_their_calendar_is_connected(self):
        _applicant, event = self._booked_event(applicant_name='Synced Organiser')
        account = self.env['google.calendar.credentials'].create({
            'calendar_token': 'fake-access-token',
            'calendar_rtoken': 'fake-refresh-token',
        })
        self.interviewer.google_calendar_account_id = account.id
        self.assertEqual(
            event._get_event_user(), self.interviewer,
            "A connected interviewer is who the event is inserted as, so the "
            "Meet lands in their calendar.")

    def test_without_a_connected_calendar_the_organiser_is_skipped(self):
        """The quiet failure: the booking still succeeds, the link never comes.

        `_google_insert` is a no-op when the acting user has no token, so an
        unconnected interviewer means the event simply never reaches Google —
        no error, no link, a candidate holding an invite with nothing to join.
        """
        _applicant, event = self._booked_event(applicant_name='Unsynced Organiser')
        self.assertFalse(self.interviewer.sudo().google_calendar_token)
        self.assertNotEqual(event._get_event_user(), self.interviewer)

    def test_the_config_warns_when_nobody_is_connected(self):
        self.cfg.invalidate_recordset(
            ['call_warn_staff_unsynced', 'call_warn_unsynced_breaks_meet'])
        self.assertTrue(
            self.cfg.call_warn_staff_unsynced,
            "An unconnected interviewer must be visible before a candidate "
            "books, not after.")
        self.assertTrue(
            self.cfg.call_warn_unsynced_breaks_meet,
            "On a google_meet type it costs the join link as well.")

    # ---- link 4: Google's answer reaches the event --------------------
    def test_hangout_link_is_written_back_after_the_insert(self):
        _applicant, event = self._booked_event(applicant_name='Written Back')
        post = event._get_post_sync_values(_google_answer(), {'id': GOOGLE_ID})
        self.assertEqual(
            post.get('videocall_location'), MEET_URL,
            "This write-back is the only thing that turns Google's answer into "
            "a link anybody can see.")

    def test_no_link_in_the_answer_writes_nothing(self):
        _applicant, event = self._booked_event(applicant_name='No Hangout')
        post = event._get_post_sync_values(_google_answer(hangout=None),
                                           {'id': GOOGLE_ID})
        self.assertNotIn('videocall_location', post)

    def test_the_recruiter_can_join_once_the_link_arrives(self):
        applicant, event = self._booked_event(applicant_name='Joinable')
        applicant.invalidate_recordset(['meet_url'])
        self.assertFalse(
            applicant.meet_url,
            "Before the sync there is nothing to join, and the cockpit must "
            "say so rather than show a dead button.")

        event.with_context(dont_notify=True).write(
            event._get_post_sync_values(_google_answer(), {'id': GOOGLE_ID}))
        applicant.invalidate_recordset(['meet_url', 'call_status'])
        self.assertEqual(applicant.meet_url, MEET_URL)
        self.assertEqual(
            applicant.action_join_call().get('url'), MEET_URL,
            "Join call must open the same link, never a second one.")
        self.assertEqual(
            event.videocall_redirection, event.videocall_location,
            "The email button and the body text must carry one identical URL.")

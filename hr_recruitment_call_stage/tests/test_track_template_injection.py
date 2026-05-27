# -*- coding: utf-8 -*-
from odoo.tests import tagged

from .common import CallStageTestCommon


@tagged('post_install', '-at_install')
class TestTrackTemplateInjection(CallStageTestCommon):
    """Verifies the booking-URL injection path the same way the foundation
    tests verify _track_template — by calling it directly.

    Rationale: Odoo's mail tracking framework hooks into
    ``cr.precommit`` (mail_thread.py:501) so the template hook runs at
    commit time. In TransactionCase tests the transaction never commits,
    so we call the method directly to assert on its return shape, just
    like ``test_template_fallback.TestTemplateFallback.test_track_*``.
    """
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.template = cls.env['mail.template'].create({
            'name': 'Test Call Invite CS',
            'model_id': cls.env.ref('hr_recruitment.model_hr_applicant').id,
            'subject': 'Book your call',
            'body_html': '<a t-att-href="ctx.get(\'booking_url\') or \'\'">link</a>',
        })

    def _enable_call_stage(self, job, appt_type):
        cfg = self._get_config(job, self.stage_call)
        cfg.write({
            'is_call_stage': True,
            'booking_appointment_type_id': appt_type.id,
            'mail_template_id': self.template.id,
        })
        return cfg

    def _fire_track(self, applicant):
        """Mirror the production tracking path: applicant.stage_id is now
        on the call stage, and the mail framework would call
        _track_template({'stage_id'}) at precommit. Call it directly.
        """
        return applicant._track_template({'stage_id'})

    def test_booking_invite_created_on_first_transition(self):
        self._enable_call_stage(self.job_designer, self.appt_hr_call)
        applicant = self._make_applicant('Anna CS', self.job_designer)
        applicant.stage_id = self.stage_call.id
        self._fire_track(applicant)

        invite = self._find_invite(applicant, self.appt_hr_call)
        self.assertTrue(invite)
        self.assertTrue(invite.book_url)

    def test_booking_url_injected_in_context(self):
        self._enable_call_stage(self.job_designer, self.appt_hr_call)
        applicant = self._make_applicant('Anna2 CS', self.job_designer)
        applicant.stage_id = self.stage_call.id
        res = self._fire_track(applicant)
        self.assertIn('stage_id', res)
        template_record, _opts = res['stage_id']
        # The template record returned must carry booking_url in its context.
        self.assertIn('booking_url', template_record._context)
        self.assertTrue(template_record._context['booking_url'])

    def test_subsequent_transition_reuses_invite(self):
        self._enable_call_stage(self.job_designer, self.appt_hr_call)
        applicant = self._make_applicant('Bohdan CS', self.job_designer)
        applicant.stage_id = self.stage_call.id
        self._fire_track(applicant)
        first_invite = self._find_invite(applicant, self.appt_hr_call)
        self.assertTrue(first_invite)

        # Move out and back.
        new_stage = self.Stage.create({
            'name': 'Tmp parking CS', 'sequence': 25,
        })
        applicant.stage_id = new_stage.id
        applicant.stage_id = self.stage_call.id
        self._fire_track(applicant)

        invites_all = self.AppointmentInvite.sudo().search([
            ('applicant_id', '=', applicant.id),
        ])
        self.assertEqual(len(invites_all), 1)
        self.assertEqual(invites_all, first_invite,
                         "Re-entering the stage must reuse the existing invite")

    def test_two_jobs_two_different_urls(self):
        self._enable_call_stage(self.job_designer, self.appt_hr_call)
        self._enable_call_stage(self.job_engineer, self.appt_tech_call)
        a1 = self._make_applicant('Anna CS', self.job_designer)
        a2 = self._make_applicant('Bohdan CS', self.job_engineer)
        a1.stage_id = self.stage_call.id
        a2.stage_id = self.stage_call.id
        self._fire_track(a1)
        self._fire_track(a2)

        i1 = self._find_invite(a1, self.appt_hr_call)
        i2 = self._find_invite(a2, self.appt_tech_call)
        self.assertNotEqual(i1, i2)
        self.assertNotEqual(i1.book_url, i2.book_url)
        self.assertIn(self.appt_hr_call, i1.appointment_type_ids)
        self.assertIn(self.appt_tech_call, i2.appointment_type_ids)

    def test_partner_minted_when_applicant_has_none(self):
        # Stock hr.applicant tends to auto-link a partner from email_from
        # via _compute_partner_phone_email. Force a no-partner scenario by
        # nulling partner_id after create — this exercises the
        # _ensure_partner_for_booking branch deterministically.
        self._enable_call_stage(self.job_designer, self.appt_hr_call)
        applicant = self.Applicant.create({
            'name': 'Carla CS',
            'partner_name': 'Carla CS',
            'job_id': self.job_designer.id,
            'email_from': 'carla.cs@example.invalid',
        })
        # Hard-clear partner so the invite-mint path must create one.
        applicant.partner_id = False
        applicant.stage_id = self.stage_call.id
        self._fire_track(applicant)
        applicant.invalidate_recordset(['partner_id'])
        self.assertTrue(applicant.partner_id,
                        "Partner must be auto-created for booking")
        self.assertEqual(applicant.partner_id.email, 'carla.cs@example.invalid')

    def test_non_call_stage_does_not_inject(self):
        cfg = self._get_config(self.job_designer, self.stage_call)
        cfg.write({'mail_template_id': self.template.id})
        applicant = self._make_applicant('Dmytro CS', self.job_designer)
        applicant.stage_id = self.stage_call.id
        self._fire_track(applicant)
        invites = self.AppointmentInvite.sudo().search([
            ('applicant_id', '=', applicant.id),
        ])
        self.assertFalse(invites,
                         "No invite should be minted for a non-call stage")

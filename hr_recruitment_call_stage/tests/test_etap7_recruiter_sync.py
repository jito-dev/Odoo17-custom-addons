# -*- coding: utf-8 -*-
"""Etap 7 (v17.0.6.0.0) — regression tests covering:

A. The new ``recruiter_user_ids`` sync into
   ``appointment.type.staff_user_ids`` with UNION semantics.
B. The unconditional v17.0.6.0.0 pre-migrate body rewrite — including
   the "broken body without legacy marker" case that the 17.0.5.0.0
   sweep missed.
C. End-to-end render path: the ``Book a call`` button appears in the
   email sent by ``action_send_invite_email`` and points at the
   resolved ``booking_url``.
"""
import importlib.util
import os

from odoo.tests import tagged

from .common import CallStageTestCommon


# Body that is "broken" in the v17.0.6 sense (ctx.get without the
# object.booking_url companion) but does NOT carry the legacy
# fallback marker. The 17.0.5 sweep would skip it; 17.0.6 must
# rewrite it.
_BROKEN_NON_LEGACY_BODY = """
<div style="margin:0px;padding:0px;font-size:14px;">
    <p>Hi <t t-out="object.partner_name or object.name or ''"/>,</p>
    <p>Pick a slot:</p>
    <p t-if="ctx.get('booking_url')">
        <a t-att-href="ctx.get('booking_url')">Book a call</a>
    </p>
</div>
""".strip()


def _load_v6_migration():
    here = os.path.dirname(__file__)
    path = os.path.normpath(os.path.join(
        here, '..', 'migrations', '17.0.6.0.0', 'pre-migrate.py'))
    spec = importlib.util.spec_from_file_location(
        'hr_recruitment_call_stage_17_0_6_0_0_pre_migrate', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@tagged('post_install', '-at_install')
class TestEtap7RecruiterSync(CallStageTestCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Users = cls.env['res.users']
        cls.recruiter_a = Users.create({
            'name': 'Recruiter Alpha CS',
            'login': 'recruiter_alpha_cs@example.com',
            'email': 'recruiter_alpha_cs@example.com',
        })
        cls.recruiter_b = Users.create({
            'name': 'Recruiter Beta CS',
            'login': 'recruiter_beta_cs@example.com',
            'email': 'recruiter_beta_cs@example.com',
        })
        cls.recruiter_c = Users.create({
            'name': 'Recruiter Gamma CS',
            'login': 'recruiter_gamma_cs@example.com',
            'email': 'recruiter_gamma_cs@example.com',
        })

    # ---- 7.1 (v17.0.24.0.0): recruiter_user_ids sync is NEUTRALISED ----
    # The "Booking calendars" field is hidden and no longer drives the pool;
    # the Appointment Type owns its staff_user_ids directly. Writing
    # recruiter_user_ids must NOT mutate the type's staff anymore.
    def test_recruiter_user_ids_no_longer_syncs_to_staff(self):
        self.appt_hr_call.staff_user_ids = [(6, 0, [self.recruiter_c.id])]
        cfg = self._get_config(self.job_designer, self.stage_call)
        cfg.write({
            'is_call_stage': True,
            'booking_appointment_type_id': self.appt_hr_call.id,
            'recruiter_user_ids': [(6, 0, [
                self.recruiter_a.id, self.recruiter_b.id])],
        })
        self.appt_hr_call.invalidate_recordset(['staff_user_ids'])
        staff = self.appt_hr_call.staff_user_ids
        self.assertNotIn(self.recruiter_a, staff,
            "neutralised sync must NOT push recruiter_user_ids into staff")
        self.assertNotIn(self.recruiter_b, staff,
            "neutralised sync must NOT push recruiter_user_ids into staff")
        self.assertIn(self.recruiter_c, staff,
            "appt.type's own staff (the source of truth) must be untouched")

    # ---- 7.2: Appointment Type staff is the single source of truth ----
    def test_appt_type_staff_is_source_of_truth(self):
        # Staff set directly on the appointment.type form must survive a
        # Call Stage save — this is now the ONLY supported way.
        self.appt_hr_call.staff_user_ids = [(6, 0, [self.recruiter_c.id])]
        cfg = self._get_config(self.job_designer, self.stage_call)
        cfg.write({
            'is_call_stage': True,
            'booking_appointment_type_id': self.appt_hr_call.id,
        })
        self.appt_hr_call.invalidate_recordset(['staff_user_ids'])
        self.assertIn(self.recruiter_c, self.appt_hr_call.staff_user_ids,
            "appt.type staff set directly must survive a Call Stage save")

    # ---- 7.6: pre-migrate 17.0.6 rewrites broken-non-legacy body -----
    def test_migrate_v6_rewrites_broken_non_legacy_body(self):
        MailTemplate = self.env['mail.template']
        applicant_model_id = self.env.ref(
            'hr_recruitment.model_hr_applicant').id
        broken = MailTemplate.create({
            'name': 'Broken non-legacy CS',
            'model_id': applicant_model_id,
            'subject': 'X',
            'body_html': _BROKEN_NON_LEGACY_BODY,
        })
        # The body must be wired through a Call Stage config for the
        # v6 sweep to claim it. Enable the Call Stage with a valid
        # (auto-filled) template first, then wire the broken template via
        # raw SQL — this reproduces a legacy pre-constraint row (the
        # config-time constraint now rejects a button-less template, so a
        # broken row can only exist as legacy data the migration repairs).
        cfg = self._get_config(self.job_designer, self.stage_call)
        cfg.write({
            'is_call_stage': True,
            'booking_appointment_type_id': self.appt_hr_call.id,
        })
        # Flush pending ORM writes (the auto-filled template) to DB BEFORE the
        # raw SQL so the SQL value sticks and is not clobbered by a later flush.
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE hr_job_stage_config SET mail_template_id=%s WHERE id=%s",
            (broken.id, cfg.id),
        )
        cfg.invalidate_recordset(['mail_template_id'])

        # Sanity: legacy marker absent — v17.0.5 sweep would NOT
        # have touched this body.
        self.assertNotIn('Booking link unavailable', broken.body_html)
        self.assertNotIn('object.booking_url', broken.body_html)

        _load_v6_migration().migrate(self.env.cr, '17.0.6.0.0')
        broken.invalidate_recordset(['body_html'])

        body = broken.body_html or ''
        self.assertIn('object.booking_url', body,
            "v6 sweep must repair broken-non-legacy bodies referenced "
            "by Call Stage configs")
        self.assertIn('Book a call', body)

    # ---- 7.7: pre-migrate 17.0.6 preserves well-formed customisations --
    def test_migrate_v6_preserves_well_formed_custom_body(self):
        MailTemplate = self.env['mail.template']
        applicant_model_id = self.env.ref(
            'hr_recruitment.model_hr_applicant').id
        # Well-formed: reads object.booking_url, guarded, no legacy marker.
        well_formed = (
            '<p>Hi — <a t-if="object.booking_url" '
            't-att-href="object.booking_url">pick a slot</a></p>'
        )
        custom = MailTemplate.create({
            'name': 'Well-formed custom CS',
            'model_id': applicant_model_id,
            'subject': 'X',
            'body_html': well_formed,
        })
        cfg = self._get_config(self.job_designer, self.stage_call)
        cfg.write({
            'is_call_stage': True,
            'booking_appointment_type_id': self.appt_hr_call.id,
            'mail_template_id': custom.id,
        })
        before = custom.body_html

        _load_v6_migration().migrate(self.env.cr, '17.0.6.0.0')
        custom.invalidate_recordset(['body_html'])

        self.assertEqual(custom.body_html, before,
            "well-formed custom body must be left byte-identical")

    # ---- 7.8: end-to-end button render with auto-minted URL ----------
    def test_action_send_invite_renders_button_with_url(self):
        cfg = self._get_config(self.job_designer, self.stage_call)
        cfg.write({
            'is_call_stage': True,
            'booking_appointment_type_id': self.appt_hr_call.id,
        })
        applicant = self._make_applicant(
            'Anna E2E CS', self.job_designer, self.stage_call)

        # Ensure the body is fresh (mirrors a real upgrade flow).
        _load_v6_migration().migrate(self.env.cr, '17.0.6.0.0')

        applicant.action_send_invite_email()
        mail = self.env['mail.mail'].sudo().search([
            ('model', '=', 'hr.applicant'),
            ('res_id', '=', applicant.id),
        ], order='id desc', limit=1)
        self.assertTrue(mail, "send must queue a mail.mail")
        body = mail.body_html or mail.body or ''
        # Button label is present AND the href points at the auto-minted
        # Appointments booking URL.
        booking_url = applicant._get_current_invite().book_url
        self.assertTrue(booking_url,
            "an Appointments invite must be minted on send")
        self.assertIn('Book a call', body,
            "button label must render")
        self.assertIn(booking_url, body,
            "button href must resolve to the auto-minted booking URL")
        self.assertNotIn('Booking link unavailable', body)

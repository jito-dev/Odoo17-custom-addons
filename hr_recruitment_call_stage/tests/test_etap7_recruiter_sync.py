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

    # ---- 7.1: simple sync — recruiters become THE staff pool --------
    def test_simple_sync_sets_recruiters_as_staff(self):
        cfg = self._get_config(self.job_designer, self.stage_call)
        cfg.write({
            'is_call_stage': True,
            'booking_appointment_type_id': self.appt_hr_call.id,
            'recruiter_user_ids': [(6, 0, [
                self.recruiter_a.id, self.recruiter_b.id])],
        })
        self.appt_hr_call.invalidate_recordset(['staff_user_ids'])
        staff = self.appt_hr_call.staff_user_ids
        # Opt-in mode: appt_type.staff becomes EXACTLY the union of
        # sibling configs' recruiter_user_ids — no more, no less.
        self.assertEqual(set(staff.ids),
            {self.recruiter_a.id, self.recruiter_b.id},
            "opt-in sync must REPLACE staff with the recruiters union")

    # ---- 7.2: UNION across two configs sharing an appt_type ----------
    def test_union_across_configs_same_appt_type(self):
        cfg_designer = self._get_config(self.job_designer, self.stage_call)
        cfg_engineer = self._get_config(self.job_engineer, self.stage_call)
        cfg_designer.write({
            'is_call_stage': True,
            'booking_appointment_type_id': self.appt_hr_call.id,
            'recruiter_user_ids': [(6, 0, [self.recruiter_a.id])],
        })
        cfg_engineer.write({
            'is_call_stage': True,
            'booking_appointment_type_id': self.appt_hr_call.id,
            'recruiter_user_ids': [(6, 0, [self.recruiter_b.id])],
        })
        self.appt_hr_call.invalidate_recordset(['staff_user_ids'])
        staff = self.appt_hr_call.staff_user_ids
        self.assertIn(self.recruiter_a, staff,
            "stage A's recruiter must be in the pool")
        self.assertIn(self.recruiter_b, staff,
            "stage B's recruiter must NOT be evicted by stage A's save")

    # ---- 7.3: UNION never subtracts ---------------------------------
    def test_union_never_removes_other_configs_recruiters(self):
        cfg_designer = self._get_config(self.job_designer, self.stage_call)
        cfg_engineer = self._get_config(self.job_engineer, self.stage_call)
        cfg_designer.write({
            'is_call_stage': True,
            'booking_appointment_type_id': self.appt_hr_call.id,
            'recruiter_user_ids': [(6, 0, [
                self.recruiter_a.id, self.recruiter_c.id])],
        })
        cfg_engineer.write({
            'is_call_stage': True,
            'booking_appointment_type_id': self.appt_hr_call.id,
            'recruiter_user_ids': [(6, 0, [self.recruiter_b.id])],
        })
        # Recruiter A bows out of the Designer pool — but B still names
        # nobody from A's set, so staff must still contain A removal
        # behaviour is UNION: A persists only if SOMEONE still names her.
        cfg_designer.write({
            'recruiter_user_ids': [(6, 0, [self.recruiter_c.id])],
        })
        self.appt_hr_call.invalidate_recordset(['staff_user_ids'])
        staff = self.appt_hr_call.staff_user_ids
        self.assertNotIn(self.recruiter_a, staff,
            "recruiter A removed from every config — must drop from pool")
        self.assertIn(self.recruiter_b, staff,
            "recruiter B still on Engineer config — must remain")
        self.assertIn(self.recruiter_c, staff,
            "recruiter C still on Designer config — must remain")

    # ---- 7.4: empty recruiter_user_ids does NOT touch staff ----------
    def test_empty_recruiters_leaves_staff_alone(self):
        # Pre-seed staff list manually on the appointment type — this
        # simulates a recruiter who set the pool directly on the
        # appointment.type form, never via the Call Stage config.
        self.appt_hr_call.staff_user_ids = [(6, 0, [self.recruiter_c.id])]
        cfg = self._get_config(self.job_designer, self.stage_call)
        cfg.write({
            'is_call_stage': True,
            'booking_appointment_type_id': self.appt_hr_call.id,
            # No recruiter_user_ids on the config row.
        })
        self.appt_hr_call.invalidate_recordset(['staff_user_ids'])
        self.assertIn(self.recruiter_c, self.appt_hr_call.staff_user_ids,
            "appt.type staff set directly must survive when no config "
            "declares recruiters")

    # ---- 7.5: changing booking_appointment_type_id re-syncs ----------
    def test_switching_appt_type_syncs_new_target(self):
        cfg = self._get_config(self.job_designer, self.stage_call)
        cfg.write({
            'is_call_stage': True,
            'booking_appointment_type_id': self.appt_hr_call.id,
            'recruiter_user_ids': [(6, 0, [self.recruiter_a.id])],
        })
        # Now flip the appointment type — sync must run for the new
        # target. The OLD target keeps the recruiter (UNION never
        # subtracts; that's fine — abandoned types are recruiter's
        # housekeeping).
        cfg.write({'booking_appointment_type_id': self.appt_tech_call.id})
        self.appt_tech_call.invalidate_recordset(['staff_user_ids'])
        self.assertIn(self.recruiter_a, self.appt_tech_call.staff_user_ids,
            "switching appointment type must propagate recruiter "
            "to the new target")

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
        # v6 sweep to claim it.
        cfg = self._get_config(self.job_designer, self.stage_call)
        cfg.write({
            'is_call_stage': True,
            'booking_appointment_type_id': self.appt_hr_call.id,
            'mail_template_id': broken.id,
        })

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

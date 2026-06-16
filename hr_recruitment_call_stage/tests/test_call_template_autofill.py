# -*- coding: utf-8 -*-
"""Tests for v17.0.1.1.0 — auto-fill mail_template_id on is_call_stage flip.

Covers both UX entry points:
  * direct write() on hr.job.stage.config (popup form);
  * create() with is_call_stage=True (programmatic / wizard);
  * hr.job.stage.create.wizard with is_call_stage=True (form path).

Contracts verified:
  - Empty mail_template_id at flip-on → shipped template injected.
  - Pre-existing mail_template_id at flip-on → preserved (no overwrite).
  - Vals carrying both is_call_stage=True and an explicit mail_template_id
    → explicit value wins (no overwrite).
  - Untick path (is_call_stage False) → mail_template_id untouched.
  - Multi-record write: only rows with empty mail_template_id are filled;
    rows with existing overrides survive.
"""
from odoo.tests import tagged

from .common import CallStageTestCommon


_CALL_INVITE_XMLID = (
    'hr_recruitment_call_stage.mail_template_call_invite_generic'
)


@tagged('post_install', '-at_install')
class TestCallTemplateAutofill(CallStageTestCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.shipped_template = cls.env.ref(_CALL_INVITE_XMLID)
        # An alternative template a recruiter might pick to test override
        # preservation. Model must be hr.applicant per foundation constraint.
        cls.alt_template = cls.env['mail.template'].create({
            'name': 'CS alt template',
            'model_id': cls.env.ref('hr_recruitment.model_hr_applicant').id,
            'subject': 'Alt subject',
            # Must carry a Book-a-call button (object.booking_url) so the
            # call-stage config constraint accepts it as a valid call-invite
            # template — this template is used to verify auto-fill/override
            # behaviour, not body content.
            'body_html': '<p>Alt body</p>'
                         '<a t-att-href="object.booking_url">Book a call</a>',
        })

    def test_write_fills_template_when_empty(self):
        cfg = self._get_config(self.job_designer, self.stage_call)
        self.assertFalse(cfg.mail_template_id,
            "precondition: row starts with no template override")
        cfg.write({
            'is_call_stage': True,
            'booking_appointment_type_id': self.appt_hr_call.id,
        })
        self.assertEqual(cfg.mail_template_id, self.shipped_template,
            "ticking is_call_stage on a row without a template must inject "
            "the shipped call-invite template")

    def test_write_preserves_existing_template_override(self):
        cfg = self._get_config(self.job_designer, self.stage_call)
        cfg.mail_template_id = self.alt_template
        cfg.write({
            'is_call_stage': True,
            'booking_appointment_type_id': self.appt_hr_call.id,
        })
        self.assertEqual(cfg.mail_template_id, self.alt_template,
            "recruiter-set template must survive is_call_stage toggle-on")

    def test_write_with_explicit_template_in_vals_wins(self):
        cfg = self._get_config(self.job_designer, self.stage_call)
        cfg.write({
            'is_call_stage': True,
            'booking_appointment_type_id': self.appt_hr_call.id,
            'mail_template_id': self.alt_template.id,
        })
        self.assertEqual(cfg.mail_template_id, self.alt_template,
            "explicit mail_template_id in same write must NOT be overwritten "
            "by the auto-fill")

    def test_write_with_falsy_template_in_vals_still_fills(self):
        # Regression (v17.0.24.6.0): the web client sends `mail_template_id:
        # False` when the field is rendered empty. A FALSY value in vals must
        # NOT suppress the auto-fill (only an explicit truthy pick does).
        cfg = self._get_config(self.job_designer, self.stage_call)
        self.assertFalse(cfg.mail_template_id)
        cfg.write({
            'is_call_stage': True,
            'booking_appointment_type_id': self.appt_hr_call.id,
            'mail_template_id': False,
        })
        self.assertEqual(cfg.mail_template_id, self.shipped_template,
            "an empty/False mail_template_id in the write payload must still "
            "inject the shipped call-invite template")

    def test_config_onchange_fills_template_in_form_state(self):
        # B (v17.0.24.6.0): ticking is_call_stage in the config form pre-fills
        # the template live, before save — mirrors the wizard onchange.
        cfg = self._get_config(self.job_designer, self.stage_call)
        cfg = cfg.new(origin=cfg)
        self.assertFalse(cfg.mail_template_id,
            "precondition: row starts with no template override")
        cfg.is_call_stage = True
        cfg._onchange_is_call_stage_autofill_template()
        self.assertEqual(cfg.mail_template_id, self.shipped_template,
            "@onchange must pre-fill the shipped template in form state")

    def test_config_onchange_preserves_existing_template(self):
        cfg = self._get_config(self.job_designer, self.stage_call)
        cfg = cfg.new(origin=cfg)
        cfg.mail_template_id = self.alt_template
        cfg.is_call_stage = True
        cfg._onchange_is_call_stage_autofill_template()
        self.assertEqual(cfg.mail_template_id, self.alt_template,
            "@onchange must NOT overwrite a recruiter-set template")

    def test_untick_does_not_clear_template(self):
        cfg = self._get_config(self.job_designer, self.stage_call)
        cfg.write({
            'is_call_stage': True,
            'booking_appointment_type_id': self.appt_hr_call.id,
        })
        self.assertEqual(cfg.mail_template_id, self.shipped_template)
        cfg.write({
            'is_call_stage': False,
            'booking_appointment_type_id': False,
        })
        self.assertEqual(cfg.mail_template_id, self.shipped_template,
            "unticking is_call_stage must leave the template intact "
            "(recruiter may want to keep it as the per-job default)")

    def test_idempotent_re_tick_no_overwrite(self):
        cfg = self._get_config(self.job_designer, self.stage_call)
        cfg.write({
            'is_call_stage': True,
            'booking_appointment_type_id': self.appt_hr_call.id,
        })
        # Customise after the first tick.
        cfg.mail_template_id = self.alt_template
        # Second write that re-asserts is_call_stage=True must NOT re-trigger
        # the auto-fill (rows_enabling filters to previously-False rows).
        cfg.write({'is_call_stage': True})
        self.assertEqual(cfg.mail_template_id, self.alt_template,
            "re-asserting is_call_stage=True must not overwrite the customised "
            "template")

    def test_multi_record_write_per_row_decision(self):
        cfg_d = self._get_config(self.job_designer, self.stage_call)
        cfg_e = self._get_config(self.job_engineer, self.stage_call)
        # Designer keeps row empty; engineer has a custom override.
        cfg_e.mail_template_id = self.alt_template
        # Single multi-record write toggling both rows on. Appointment type
        # must be set on both to satisfy the @api.constrains.
        rows = cfg_d | cfg_e
        rows.write({
            'is_call_stage': True,
            'booking_appointment_type_id': self.appt_hr_call.id,
        })
        self.assertEqual(cfg_d.mail_template_id, self.shipped_template,
            "row without a template gets the shipped default")
        self.assertEqual(cfg_e.mail_template_id, self.alt_template,
            "row with a recruiter override is left alone")

    def test_create_with_is_call_stage_injects_default(self):
        # Foundation create() may have produced a row for (job_designer,
        # stage_call) already; unlink so we exercise the create path here.
        existing = self._get_config(self.job_designer, self.stage_call)
        if existing:
            existing.unlink()
        cfg = self.Config.create({
            'job_id': self.job_designer.id,
            'stage_id': self.stage_call.id,
            'is_call_stage': True,
            'booking_appointment_type_id': self.appt_hr_call.id,
        })
        self.assertEqual(cfg.mail_template_id, self.shipped_template,
            "create() with is_call_stage=True and no template must inject "
            "the shipped default")

    def test_create_with_explicit_template_wins(self):
        existing = self._get_config(self.job_designer, self.stage_call)
        if existing:
            existing.unlink()
        cfg = self.Config.create({
            'job_id': self.job_designer.id,
            'stage_id': self.stage_call.id,
            'is_call_stage': True,
            'booking_appointment_type_id': self.appt_hr_call.id,
            'mail_template_id': self.alt_template.id,
        })
        self.assertEqual(cfg.mail_template_id, self.alt_template,
            "explicit mail_template_id in create vals must NOT be overwritten")

    def test_wizard_action_create_with_is_call_stage(self):
        Wizard = self.env['hr.job.stage.create.wizard']
        wiz = Wizard.create({
            'job_id': self.job_designer.id,
            'name': 'Wizard-born call stage CS',
            'sequence': 55,
            'is_call_stage': True,
            'booking_appointment_type_id': self.appt_hr_call.id,
        })
        # Mimic the onchange: in form view it would have auto-filled the
        # template. Here we exercise the server-side fallback by leaving
        # mail_template_id empty; the config-row write override fills it.
        wiz.action_create()
        Stage = self.env['hr.recruitment.stage']
        stage = Stage.search([
            ('job_ids', 'in', self.job_designer.id),
            ('name', '=', 'Wizard-born call stage CS'),
        ], limit=1)
        self.assertTrue(stage,
            "wizard must create the hr.recruitment.stage")
        cfg = self._get_config(self.job_designer, stage)
        self.assertTrue(cfg,
            "wizard must create the (job, stage) config row")
        self.assertTrue(cfg.is_call_stage,
            "is_call_stage must be stamped on the config row")
        self.assertEqual(cfg.booking_appointment_type_id, self.appt_hr_call)
        self.assertEqual(cfg.mail_template_id, self.shipped_template,
            "wizard-created config with is_call_stage=True must end up with "
            "the shipped template via the config-write auto-fill")

    def test_wizard_onchange_fills_template_in_form_state(self):
        Wizard = self.env['hr.job.stage.create.wizard']
        wiz = Wizard.new({
            'job_id': self.job_designer.id,
            'name': 'Onchange-driven CS',
            'sequence': 56,
        })
        self.assertFalse(wiz.mail_template_id,
            "precondition: wizard starts with no template")
        wiz.is_call_stage = True
        wiz._onchange_is_call_stage_autofill_template()
        self.assertEqual(wiz.mail_template_id, self.shipped_template,
            "@onchange must pre-fill the shipped template in form state")

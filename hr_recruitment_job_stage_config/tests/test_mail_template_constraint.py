# -*- coding: utf-8 -*-
"""PR 2.5: @api.constrains on hr.job.stage.config.mail_template_id.

A mail.template referenced from a config row must have model = hr.applicant.
Without the constraint, picking a template with model_id=NULL crashes the
mail renderer at ``self.env[self.model]`` (KeyError: False).
"""
from odoo.exceptions import ValidationError
from odoo.tests.common import tagged

from .common import StageConfigTestCommon


@tagged('post_install', '-at_install')
class TestMailTemplateConstraint(StageConfigTestCommon):
    def setUp(self):
        super().setUp()
        self.stage = self._create_stage('PR 2.5 Test Stage')
        # Auto-create from stage.create() already produced a row for every
        # job — pick that one up and clear any pre-existing mail_template_id
        # so test_clearing_template_is_allowed has a clean baseline.
        self.config = self._get_or_create_config(
            self.job_a, self.stage, mail_template_id=False)
        self.applicant_model_id = self.env['ir.model']._get_id('hr.applicant')
        self.lead_model_id = self.env['ir.model']._get_id('crm.lead') if \
            self.env['ir.model'].search([('model', '=', 'crm.lead')], limit=1) else None

    def test_valid_template_passes(self):
        tmpl = self.MailTemplate.create({
            'name': 'PR 2.5 Valid',
            'model_id': self.applicant_model_id,
            'subject': 'Hello',
            'body_html': '<p>Hi</p>',
        })
        # Must not raise
        self.config.mail_template_id = tmpl

    def test_template_with_null_model_rejected(self):
        # mail.template.model_id is required at the model level in stock
        # Odoo, but legacy data may have it cleared. Simulate that via
        # raw SQL to bypass the field constraint, then assert our
        # config-level guard catches it on write.
        tmpl = self.MailTemplate.create({
            'name': 'PR 2.5 Broken',
            'model_id': self.applicant_model_id,
            'subject': 'X',
            'body_html': '<p>X</p>',
        })
        self.env.cr.execute(
            "UPDATE mail_template SET model_id = NULL WHERE id = %s",
            (tmpl.id,),
        )
        tmpl.invalidate_recordset(['model_id', 'model'])
        with self.assertRaises(ValidationError):
            self.config.mail_template_id = tmpl

    def test_template_with_foreign_model_rejected(self):
        if not self.lead_model_id:
            self.skipTest('crm module not installed')
        tmpl = self.MailTemplate.create({
            'name': 'PR 2.5 Foreign Model',
            'model_id': self.lead_model_id,
            'subject': 'X',
            'body_html': '<p>X</p>',
        })
        with self.assertRaises(ValidationError):
            self.config.mail_template_id = tmpl

    def test_clearing_template_is_allowed(self):
        # Empty mail_template_id is the fallback-to-stage-default state
        # and must always be allowed regardless of historical templates.
        self.config.mail_template_id = False  # no raise

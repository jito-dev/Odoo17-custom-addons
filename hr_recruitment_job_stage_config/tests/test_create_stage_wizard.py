# -*- coding: utf-8 -*-
"""Tests for the create-job-specific-stage wizard.

- Creates a new hr.recruitment.stage with scope='specific' and job_ids
  containing only the current job.
- Pre-fills payload from a source job-specific stage's config row
  (per-job email override, requirements, test task, links).
"""
from .common import StageConfigTestCommon


class TestCreateStageWizard(StageConfigTestCommon):

    def test_wizard_creates_specific_stage_with_config(self):
        Wizard = self.env['hr.job.stage.create.wizard']
        wiz = Wizard.create({
            'job_id': self.job_a.id,
            'name': 'Custom Stage A JSC',
            'sequence': 25,
        })
        wiz.action_create()
        stage = self.Stage.search([('name', '=', 'Custom Stage A JSC')])
        self.assertTrue(stage)
        self.assertEqual(stage.scope, 'specific')
        self.assertEqual(stage.job_ids, self.job_a)
        config = self.Config.search([
            ('job_id', '=', self.job_a.id),
            ('stage_id', '=', stage.id),
        ])
        self.assertTrue(config)
        self.assertTrue(config.visible)

    def test_wizard_copies_from_template_source(self):
        template = self.MailTemplate.create({
            'name': 'JSC Template',
            'model_id': self.env['ir.model']._get('hr.applicant').id,
            'subject': 'JSC',
            'body_html': '<p>JSC</p>',
        })
        # Source: an existing job-specific stage on job_b with a per-job
        # email override + a resource link.
        source_stage = self._create_stage(
            'Source JSC', sequence=42, job_ids=[self.job_b])
        source_config = self.Config.search([
            ('job_id', '=', self.job_b.id),
            ('stage_id', '=', source_stage.id),
        ])
        source_config.write({
            'mail_template_id': template.id,
            'test_task_description': '<p>Build X JSC</p>',
            'requirements': 'JSC requirements',
        })
        self.env['hr.job.stage.config.link'].create({
            'config_id': source_config.id,
            'label': 'GitHub',
            'url': 'https://github.com/example/repo',
        })

        Wizard = self.env['hr.job.stage.create.wizard']
        # `name` is required at the DB level on the wizard model; pass a
        # placeholder so create() succeeds — the onchange below overwrites it
        # with the source stage's name, which is what this test asserts on.
        wiz = Wizard.create({'job_id': self.job_a.id, 'name': '_'})
        wiz.template_source_id = source_stage
        wiz._onchange_template_source_id()

        self.assertEqual(wiz.name, 'Source JSC')
        self.assertEqual(wiz.mail_template_id, template,
                         'Email override on source config must propagate.')
        self.assertEqual(wiz.requirements, 'JSC requirements')
        self.assertEqual(len(wiz.link_ids), 1)
        self.assertEqual(wiz.link_ids.label, 'GitHub')

        wiz.action_create()
        new_stage = self.Stage.search([
            ('name', '=', 'Source JSC'),
            ('job_ids', 'in', self.job_a.id),
        ])
        self.assertTrue(new_stage)
        self.assertNotEqual(new_stage, source_stage,
                            'Wizard must create an independent stage.')
        new_config = self.Config.search([
            ('job_id', '=', self.job_a.id),
            ('stage_id', '=', new_stage.id),
        ])
        self.assertEqual(new_config.mail_template_id, template)
        self.assertEqual(len(new_config.link_ids), 1)
        self.assertEqual(new_config.link_ids.url,
                         'https://github.com/example/repo')

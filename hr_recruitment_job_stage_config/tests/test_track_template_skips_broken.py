# -*- coding: utf-8 -*-
"""PR 2.5: runtime guard in _track_template.

If a config row has a broken template (model_id NULL or non-applicant
model) — possible on legacy DBs even after pre-migrate, e.g. via raw
SQL writes — moving an applicant through that stage must NOT crash the
mail renderer. The guard:
  * pops the stage_id entry from the tracking template dict,
  * logs an error,
  * posts a chatter message on the applicant so the recruiter sees it.
"""
from odoo.tests.common import tagged

from .common import StageConfigTestCommon


@tagged('post_install', '-at_install')
class TestTrackTemplateSkipsBroken(StageConfigTestCommon):
    def setUp(self):
        super().setUp()
        self.stage_a = self._create_stage('PR 2.5 Track A', sequence=10)
        self.stage_b = self._create_stage('PR 2.5 Track B', sequence=20)
        self.applicant_model_id = self.env['ir.model']._get_id('hr.applicant')
        self.tmpl = self.MailTemplate.create({
            'name': 'PR 2.5 Track Tmpl',
            'model_id': self.applicant_model_id,
            'subject': 'X',
            'body_html': '<p>X</p>',
        })
        self.config = self._get_or_create_config(
            self.job_a, self.stage_b, mail_template_id=self.tmpl.id)
        # Break the FK out-of-band (simulates legacy broken data).
        self.env.cr.execute(
            "UPDATE mail_template SET model_id = NULL WHERE id = %s",
            (self.tmpl.id,),
        )
        # ``flush=False`` so the cached model_id=applicant_model_id is NOT
        # flushed back onto the row we just raw-NULLed. See
        # test_pre_migrate_cleanup.py for the same gotcha.
        self.tmpl.invalidate_recordset(['model_id', 'model'], flush=False)

        self.applicant = self._create_applicant(
            'PR 2.5 Track Cand', self.job_a, stage=self.stage_a,
        )

    def test_move_does_not_crash(self):
        # Without the guard this would crash at self.env[self.model] in
        # mail_template._generate_template_attachments with KeyError: False.
        self.applicant.stage_id = self.stage_b
        self.applicant.flush_recordset()

    def test_chatter_message_posted(self):
        before = self.applicant.message_ids
        self.applicant.stage_id = self.stage_b
        self.applicant.flush_recordset()
        new_messages = self.applicant.message_ids - before
        bodies = ' '.join(new_messages.mapped('body') or [])
        self.assertIn('misconfigured', bodies)

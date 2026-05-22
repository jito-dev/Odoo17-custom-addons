# -*- coding: utf-8 -*-
from .common import StageConfigTestCommon


class TestTemplateFallback(StageConfigTestCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.applicant_model_id = cls.env.ref(
            'hr_recruitment.model_hr_applicant').id
        cls.global_template = cls.MailTemplate.create({
            'name': 'JSC global stage template',
            'model_id': cls.applicant_model_id,
            'subject': 'Global subject',
            'body_html': '<p>global body</p>',
        })
        cls.job_template = cls.MailTemplate.create({
            'name': 'JSC job override template',
            'model_id': cls.applicant_model_id,
            'subject': 'Per-job subject',
            'body_html': '<p>per-job body</p>',
        })
        cls.stage = cls._create_stage(
            'JSC tplfb stage', template_id=cls.global_template.id)

    def test_effective_template_falls_back_to_stage(self):
        cfg = self.Config.create({
            'job_id': self.job_a.id,
            'stage_id': self.stage.id,
        })
        self.assertEqual(cfg.effective_mail_template_id, self.global_template,
            "with no override, effective template equals stage.template_id")

    def test_effective_template_uses_override(self):
        cfg = self.Config.create({
            'job_id': self.job_a.id,
            'stage_id': self.stage.id,
            'mail_template_id': self.job_template.id,
        })
        self.assertEqual(cfg.effective_mail_template_id, self.job_template,
            "with override set, effective template equals override")

    def test_track_template_uses_config_override(self):
        self.Config.create({
            'job_id': self.job_a.id,
            'stage_id': self.stage.id,
            'mail_template_id': self.job_template.id,
        })
        applicant = self.Applicant.create({
            'partner_name': 'JSC tplfb applicant A',
            'job_id': self.job_a.id,
        })
        applicant.stage_id = self.stage
        res = applicant._track_template({'stage_id': self.stage.id})
        self.assertIn('stage_id', res)
        template_record, _kwargs = res['stage_id']
        self.assertEqual(template_record, self.job_template,
            "_track_template must resolve to per-job override")

    def test_track_template_fallback_to_stage(self):
        """No config row → stock fallback to stage.template_id."""
        applicant = self.Applicant.create({
            'partner_name': 'JSC tplfb applicant B',
            'job_id': self.job_b.id,
        })
        applicant.stage_id = self.stage
        res = applicant._track_template({'stage_id': self.stage.id})
        self.assertIn('stage_id', res)
        template_record, _ = res['stage_id']
        self.assertEqual(template_record, self.global_template)

    def test_track_template_no_template_anywhere(self):
        empty_stage = self._create_stage('JSC tplfb empty stage')
        applicant = self.Applicant.create({
            'partner_name': 'JSC tplfb applicant C',
            'job_id': self.job_a.id,
        })
        applicant.stage_id = empty_stage
        res = applicant._track_template({'stage_id': empty_stage.id})
        self.assertNotIn('stage_id', res,
            "no template anywhere → no stage_id entry in res")

    def test_track_template_company_consistency_check(self):
        """Cross-company template assignment must raise ValidationError."""
        from odoo.exceptions import ValidationError
        other_company = self.env['res.company'].create({
            'name': 'JSC tplfb other co'})
        other_template = self.MailTemplate.with_context(
            default_company_id=other_company.id,
        ).create({
            'name': 'JSC tplfb cross-co tpl',
            'model_id': self.applicant_model_id,
            'subject': 'cross',
            'body_html': 'cross',
            'company_id': other_company.id,
        })
        with self.assertRaises(ValidationError):
            self.Config.create({
                'job_id': self.job_a.id,  # job_a's company differs
                'stage_id': self.stage.id,
                'mail_template_id': other_template.id,
            })

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
        # Clear any per-job override left over from setUpClass auto-creation.
        cfg = self._get_or_create_config(self.job_a, self.stage,
                                          mail_template_id=False)
        self.assertEqual(cfg.effective_mail_template_id, self.global_template,
            "with no override, effective template equals stage.template_id")

    def test_effective_template_uses_override(self):
        cfg = self._get_or_create_config(self.job_a, self.stage,
                                          mail_template_id=self.job_template.id)
        self.assertEqual(cfg.effective_mail_template_id, self.job_template,
            "with override set, effective template equals override")

    def test_track_template_uses_config_override(self):
        self._get_or_create_config(self.job_a, self.stage,
                                    mail_template_id=self.job_template.id)
        applicant = self.Applicant.create({
            'name': 'JSC tplfb applicant A',
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
        """No per-job override → falls back to stage.template_id."""
        # Clear any per-job override on job_b for the global stage so the
        # fallback path is unambiguous.
        self._get_or_create_config(self.job_b, self.stage,
                                    mail_template_id=False)
        applicant = self.Applicant.create({
            'name': 'JSC tplfb applicant B',
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
        # Stage has no template_id; ensure the per-job config row also has
        # no override on job_a.
        self._get_or_create_config(self.job_a, empty_stage,
                                    mail_template_id=False)
        applicant = self.Applicant.create({
            'name': 'JSC tplfb applicant C',
            'partner_name': 'JSC tplfb applicant C',
            'job_id': self.job_a.id,
        })
        applicant.stage_id = empty_stage
        res = applicant._track_template({'stage_id': empty_stage.id})
        self.assertNotIn('stage_id', res,
            "no template anywhere → no stage_id entry in res")

    def test_track_template_company_consistency_check(self):
        """Cross-company template assignment must raise ValidationError.

        Stock ``mail.template`` in Odoo 17 has NO ``company_id`` field
        (see odoo17_community/addons/mail/models/mail_template.py) — the
        Many2one is added by select downstream modules that we do not
        depend on. The only @api.constrains we ship on this config's
        mail_template_id checks model/model_id consistency, not company.
        Skipping this scenario until a real cross-company constraint
        lands; leaving the test in place as a marker.
        """
        self.skipTest(
            'mail.template has no company_id in stock Odoo 17; the '
            'cross-company constraint this test asserts is not implemented '
            'on hr.job.stage.config._check_mail_template_model.'
        )

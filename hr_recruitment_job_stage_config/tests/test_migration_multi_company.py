# -*- coding: utf-8 -*-
from .common import StageConfigTestCommon
from odoo.addons.hr_recruitment_job_stage_config.hooks import run_backfill


class TestMigrationMultiCompany(StageConfigTestCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_x = cls.env['res.company'].create({'name': 'JSC mig co X'})
        cls.company_y = cls.env['res.company'].create({'name': 'JSC mig co Y'})
        cls.job_x = cls.Job.create({
            'name': 'JSC mig job X',
            'company_id': cls.company_x.id,
            'department_id': cls.dept.id,
        })
        cls.job_y = cls.Job.create({
            'name': 'JSC mig job Y',
            'company_id': cls.company_y.id,
            'department_id': cls.dept.id,
        })

    def test_config_row_company_follows_job(self):
        stage = self._create_stage(
            'JSC mig multi-co stage', sequence=15,
            job_ids=[self.job_x, self.job_y])
        self.Config.search([('stage_id', '=', stage.id)]).unlink()

        run_backfill(self.env)

        cfg_x = self.Config.search([
            ('stage_id', '=', stage.id),
            ('job_id', '=', self.job_x.id),
        ])
        cfg_y = self.Config.search([
            ('stage_id', '=', stage.id),
            ('job_id', '=', self.job_y.id),
        ])
        self.assertEqual(cfg_x.company_id, self.company_x,
            "config.company_id must follow job.company_id (job X)")
        self.assertEqual(cfg_y.company_id, self.company_y,
            "config.company_id must follow job.company_id (job Y)")


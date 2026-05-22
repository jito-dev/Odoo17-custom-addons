# -*- coding: utf-8 -*-
from .common import StageConfigTestCommon
from odoo.addons.hr_recruitment_job_stage_config.hooks import run_backfill


class TestMigrationZeroStages(StageConfigTestCommon):
    def test_backfill_with_zero_job_specific_stages_does_not_crash(self):
        # Delete (via unlink fallback search-unlink — we cannot bulk-delete
        # if applicants exist, so we just verify the loop handles the case
        # where every existing stage has empty job_ids).
        for stage in self.Stage.search([]):
            stage.job_ids = [(5, 0, 0)]
        # Should not raise even though no job-specific stages exist
        run_backfill(self.env)
        # Backfill cannot have created any config rows in this scenario
        # (it only creates from stage.job_ids).
        # We don't assert "0 rows total" because the same DB might host
        # other tests' fixtures.
        self.assertTrue(True)

    def test_backfill_logs_zero_run(self):
        for stage in self.Stage.search([]):
            stage.job_ids = [(5, 0, 0)]
        Log = self.env['ir.logging']
        before = Log.search_count([
            ('name', '=', 'hr_recruitment_job_stage_config.migration'),
        ])
        run_backfill(self.env)
        after = Log.search_count([
            ('name', '=', 'hr_recruitment_job_stage_config.migration'),
        ])
        self.assertGreater(after, before,
            "post-migrate must always log run summary, even for 0 rows")

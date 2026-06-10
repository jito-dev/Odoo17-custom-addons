# -*- coding: utf-8 -*-
from .common import StageConfigTestCommon
from odoo.addons.hr_recruitment_job_stage_config.hooks import (
    LOG_TAG, run_backfill,
)


class TestPostMigrateLogsToIrLogging(StageConfigTestCommon):
    def test_run_backfill_writes_audit_log(self):
        Log = self.env['ir.logging']
        before = Log.search_count([('name', '=', LOG_TAG)])
        run_backfill(self.env)
        after = Log.search_count([('name', '=', LOG_TAG)])
        self.assertGreater(after, before,
            "run_backfill must emit at least one ir.logging entry")

    def test_r2_verification_log_present(self):
        """The applicant.stage_id drift check must always log a result line
        (either OK or BROKEN), making the R2 guarantee testable."""
        run_backfill(self.env)
        match = self.env['ir.logging'].search([
            ('name', '=', LOG_TAG),
            ('message', 'like', 'R2 verification OK%'),
        ], limit=1)
        self.assertTrue(match,
            "R2 verification line must be present in audit log")

# -*- coding: utf-8 -*-
from .common import StageConfigTestCommon
from odoo.addons.hr_recruitment_job_stage_config.hooks import run_backfill


class TestMigrationIdempotent(StageConfigTestCommon):
    def test_backfill_creates_config_rows_for_job_specific_stages(self):
        stage = self._create_stage(
            'JSC mig backfill stage', sequence=15,
            job_ids=[self.job_a, self.job_b])

        # Clear any existing configs to simulate fresh install
        self.Config.search([('stage_id', '=', stage.id)]).unlink()
        run_backfill(self.env)

        configs = self.Config.search([('stage_id', '=', stage.id)])
        self.assertEqual(len(configs), 2)
        self.assertEqual(
            set(configs.mapped('job_id')), {self.job_a, self.job_b})

    def test_backfill_is_idempotent(self):
        stage = self._create_stage(
            'JSC mig idem stage', sequence=15, job_ids=[self.job_a])
        self.Config.search([('stage_id', '=', stage.id)]).unlink()

        run_backfill(self.env)
        first_count = self.Config.search_count([
            ('stage_id', '=', stage.id)])
        run_backfill(self.env)
        second_count = self.Config.search_count([
            ('stage_id', '=', stage.id)])

        self.assertEqual(first_count, second_count,
            "re-running backfill must not create duplicates")
        self.assertEqual(first_count, 1)

    def test_backfill_skips_global_stages(self):
        stage = self._create_stage('JSC mig global noop', sequence=15)
        run_backfill(self.env)
        self.assertFalse(self.Config.search([('stage_id', '=', stage.id)]))

    def test_backfill_does_not_touch_applicant_stage(self):
        stage = self._create_stage(
            'JSC mig safe stage', sequence=15, job_ids=[self.job_a])
        applicant = self._create_applicant(
            'JSC mig safe applicant', self.job_a, stage)
        applicant_stage_before = applicant.stage_id

        run_backfill(self.env)

        self.assertEqual(applicant.stage_id, applicant_stage_before,
            "backfill must never modify applicant.stage_id (R2)")

    def test_iq_to_cognitive_rename_idempotent(self):
        legacy = self._create_stage('IQ Test Assigned', sequence=2)
        run_backfill(self.env)
        legacy.invalidate_recordset(['name'])
        self.assertEqual(
            legacy.name, 'Cognitive Assessment Assigned',
            "legacy IQ Test stage must be renamed in-place")
        run_backfill(self.env)  # second run: nothing changes
        self.assertEqual(legacy.name, 'Cognitive Assessment Assigned')

    def test_iq_to_cognitive_rename_skipped_when_target_exists(self):
        legacy = self._create_stage('IQ Test Completed', sequence=3)
        # Create the target name first
        target = self._create_stage(
            'Cognitive Assessment Completed', sequence=4)
        run_backfill(self.env)
        legacy.invalidate_recordset(['name'])
        self.assertEqual(legacy.name, 'IQ Test Completed',
            "if target name already in use, rename is skipped")
        self.assertEqual(target.name, 'Cognitive Assessment Completed')

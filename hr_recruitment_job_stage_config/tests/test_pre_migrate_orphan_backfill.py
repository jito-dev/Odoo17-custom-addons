# -*- coding: utf-8 -*-
"""v17.0.1.0.11 pre-migrate — orphan (job, stage) backfill.

Simulates legacy data where a specific stage has its M2M edge
(hr_job_hr_recruitment_stage_rel) but no matching hr_job_stage_config
row. The pre-migrate must create the missing row with visible=TRUE,
idempotently, and log the action to ir.logging.
"""
from odoo.tests.common import tagged

from .common import StageConfigTestCommon


@tagged('post_install', '-at_install')
class TestPreMigrateOrphanBackfill(StageConfigTestCommon):

    def _import_pre_migrate(self):
        # Lazy import — the migration file lives outside the regular
        # Python package and is loaded by file path here.
        import importlib.util
        import os
        path = os.path.join(
            os.path.dirname(__file__), '..', 'migrations',
            '17.0.1.0.11', 'pre-migrate.py')
        spec = importlib.util.spec_from_file_location(
            'pre_migrate_17_0_1_0_11', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _orphan_count(self):
        self.env.cr.execute(
            """
            SELECT COUNT(*)
            FROM hr_job_hr_recruitment_stage_rel rel
            LEFT JOIN hr_job_stage_config c
                   ON c.job_id = rel.hr_job_id
                  AND c.stage_id = rel.hr_recruitment_stage_id
            WHERE c.id IS NULL
            """
        )
        return self.env.cr.fetchone()[0]

    def test_backfill_creates_missing_config_row(self):
        stage = self._create_stage('JSC Orphan Stage', job_ids=[self.job_a])
        # Backfill ran via create() — delete it to simulate legacy state.
        self.env.cr.execute(
            "DELETE FROM hr_job_stage_config WHERE job_id=%s AND stage_id=%s",
            (self.job_a.id, stage.id),
        )
        self.assertEqual(self._orphan_count(), 1,
                         'Test setup must produce one orphan')

        mod = self._import_pre_migrate()
        mod.migrate(self.env.cr, '17.0.1.0.10')

        self.assertEqual(self._orphan_count(), 0,
                         'pre-migrate must zero-out the orphan invariant')
        # The created row defaults to visible=True with stage.sequence.
        self.env.cr.execute(
            """SELECT visible, sequence FROM hr_job_stage_config
               WHERE job_id=%s AND stage_id=%s""",
            (self.job_a.id, stage.id),
        )
        row = self.env.cr.fetchone()
        self.assertEqual(row, (True, stage.sequence),
                         'Backfilled row must be visible with stage.sequence')

    def test_backfill_is_idempotent(self):
        stage = self._create_stage('JSC Orphan Idem', job_ids=[self.job_a])
        self.env.cr.execute(
            "DELETE FROM hr_job_stage_config WHERE job_id=%s AND stage_id=%s",
            (self.job_a.id, stage.id),
        )
        mod = self._import_pre_migrate()
        mod.migrate(self.env.cr, '17.0.1.0.10')
        mod.migrate(self.env.cr, '17.0.1.0.10')  # second pass — must no-op
        self.env.cr.execute(
            """SELECT COUNT(*) FROM hr_job_stage_config
               WHERE job_id=%s AND stage_id=%s""",
            (self.job_a.id, stage.id),
        )
        self.assertEqual(self.env.cr.fetchone()[0], 1,
                         'Second migrate must not duplicate the row')

    def test_backfill_logs_to_ir_logging(self):
        stage = self._create_stage('JSC Orphan Log', job_ids=[self.job_a])
        self.env.cr.execute(
            "DELETE FROM hr_job_stage_config WHERE job_id=%s AND stage_id=%s",
            (self.job_a.id, stage.id),
        )
        mod = self._import_pre_migrate()
        mod.migrate(self.env.cr, '17.0.1.0.10')
        self.env.cr.execute(
            """SELECT level, message FROM ir_logging
               WHERE name='hr_recruitment_job_stage_config.pre_migrate'
                 AND path LIKE %s
               ORDER BY id DESC LIMIT 1""",
            ('migrations/17.0.1.0.11/%',),
        )
        row = self.env.cr.fetchone()
        self.assertIsNotNone(row, 'pre-migrate must log to ir_logging')
        level, message = row
        self.assertEqual(level, 'INFO')
        self.assertIn('backfilled', message)

    def test_no_op_when_clean(self):
        # No orphans → migrate is a no-op, no log entry created.
        self.assertEqual(self._orphan_count(), 0,
                         'Fresh DB must have no orphans to start with')
        self.env.cr.execute(
            """SELECT COUNT(*) FROM ir_logging
               WHERE name='hr_recruitment_job_stage_config.pre_migrate'
                 AND path LIKE %s""",
            ('migrations/17.0.1.0.11/%',),
        )
        before = self.env.cr.fetchone()[0]

        mod = self._import_pre_migrate()
        mod.migrate(self.env.cr, '17.0.1.0.10')

        self.env.cr.execute(
            """SELECT COUNT(*) FROM ir_logging
               WHERE name='hr_recruitment_job_stage_config.pre_migrate'
                 AND path LIKE %s""",
            ('migrations/17.0.1.0.11/%',),
        )
        after = self.env.cr.fetchone()[0]
        self.assertEqual(before, after,
                         'No-op migrate must not write to ir_logging')

    def test_applicant_stage_id_unchanged_by_backfill(self):
        # R2 guarantee: pre-migrate never touches hr_applicant.stage_id.
        stage = self._create_stage('JSC R2 Stage', job_ids=[self.job_a])
        applicant = self._create_applicant('JSC R2 Applicant', self.job_a, stage=stage)
        self.env.cr.execute(
            "DELETE FROM hr_job_stage_config WHERE job_id=%s AND stage_id=%s",
            (self.job_a.id, stage.id),
        )
        before = applicant.stage_id.id

        mod = self._import_pre_migrate()
        mod.migrate(self.env.cr, '17.0.1.0.10')

        applicant.invalidate_recordset(['stage_id'])
        self.assertEqual(applicant.stage_id.id, before,
                         'applicant.stage_id must be unchanged (R2)')

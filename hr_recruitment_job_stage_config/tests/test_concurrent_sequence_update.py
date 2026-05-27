# -*- coding: utf-8 -*-
from .common import StageConfigTestCommon


class TestConcurrentSequenceUpdate(StageConfigTestCommon):
    def test_drag_reorder_preserves_distinct_sequences(self):
        """Simulate the kanban drag-reorder JSONRPC batch: writes new
        sequence values to several rows in one call. Verify uniqueness
        of the resulting per-job order."""
        s1 = self._create_stage('JSC seq one', sequence=10)
        s2 = self._create_stage('JSC seq two', sequence=20)
        s3 = self._create_stage('JSC seq three', sequence=30)

        # The stage create() override auto-materialises rows for every
        # existing job — find-or-write avoids the unique-constraint clash.
        c1 = self._get_or_create_config(self.job_a, s1, sequence=10)
        c2 = self._get_or_create_config(self.job_a, s2, sequence=20)
        c3 = self._get_or_create_config(self.job_a, s3, sequence=30)

        # Drag s3 to the top: web_resequence-style writes
        c3.sequence = 5
        c1.sequence = 15
        c2.sequence = 25

        # Filter to our three fixtures so we don't get tangled with any
        # other config rows that exist on job_a in a dirty dev DB.
        rows = self.Config.search([
            ('job_id', '=', self.job_a.id),
            ('stage_id', 'in', (s1 + s2 + s3).ids),
        ], order='sequence')
        self.assertEqual(rows.mapped('stage_id'), s3 + s1 + s2,
            "config sequence changes must reorder rows accordingly")
        # No two of OUR rows have the same sequence in this job
        sequences = rows.mapped('sequence')
        self.assertEqual(len(sequences), len(set(sequences)),
            "all sequences must be distinct after a drag operation")

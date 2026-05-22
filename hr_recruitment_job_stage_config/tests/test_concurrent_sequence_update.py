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

        c1 = self.Config.create({
            'job_id': self.job_a.id, 'stage_id': s1.id, 'sequence': 10})
        c2 = self.Config.create({
            'job_id': self.job_a.id, 'stage_id': s2.id, 'sequence': 20})
        c3 = self.Config.create({
            'job_id': self.job_a.id, 'stage_id': s3.id, 'sequence': 30})

        # Drag s3 to the top: web_resequence-style writes
        c3.sequence = 5
        c1.sequence = 15
        c2.sequence = 25

        rows = self.Config.search([('job_id', '=', self.job_a.id)],
            order='sequence')
        self.assertEqual(rows.mapped('stage_id'), s3 + s1 + s2,
            "config sequence changes must reorder rows accordingly")
        # No two rows have the same sequence in this job
        sequences = rows.mapped('sequence')
        self.assertEqual(len(sequences), len(set(sequences)),
            "all sequences must be distinct after a drag operation")

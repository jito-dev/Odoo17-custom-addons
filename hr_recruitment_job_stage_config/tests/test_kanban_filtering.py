# -*- coding: utf-8 -*-
from .common import StageConfigTestCommon


class TestKanbanFiltering(StageConfigTestCommon):
    def test_global_stage_visible_in_every_job_kanban(self):
        global_stage = self._create_stage('JSC kfg global', sequence=10)
        stages = self.Applicant.with_context(
            default_job_id=self.job_a.id,
        )._read_group_stage_ids(self.Stage.browse(), [], 'sequence')
        self.assertIn(global_stage, stages,
            "global stage must be visible in any job kanban")

    def test_specific_stage_visible_only_in_its_jobs(self):
        specific = self._create_stage(
            'JSC kfg specific', sequence=20, job_ids=[self.job_a])
        # Job A — visible
        stages_a = self.Applicant.with_context(
            default_job_id=self.job_a.id,
        )._read_group_stage_ids(self.Stage.browse(), [], 'sequence')
        self.assertIn(specific, stages_a)
        # Job B — invisible
        stages_b = self.Applicant.with_context(
            default_job_id=self.job_b.id,
        )._read_group_stage_ids(self.Stage.browse(), [], 'sequence')
        self.assertNotIn(specific, stages_b)

    def test_hide_via_config_excludes_stage_from_kanban(self):
        global_stage = self._create_stage('JSC kfg hideable', sequence=30)
        self.Config.create({
            'job_id': self.job_a.id,
            'stage_id': global_stage.id,
            'visible': False,
        })
        stages_a = self.Applicant.with_context(
            default_job_id=self.job_a.id,
        )._read_group_stage_ids(self.Stage.browse(), [], 'sequence')
        self.assertNotIn(global_stage, stages_a,
            "config.visible=False must hide stage from job kanban")
        # Other job unaffected
        stages_b = self.Applicant.with_context(
            default_job_id=self.job_b.id,
        )._read_group_stage_ids(self.Stage.browse(), [], 'sequence')
        self.assertIn(global_stage, stages_b)

    def test_hidden_stage_with_applicant_always_shown_r10(self):
        """R10 safety: even with visible=False, if an applicant currently
        lives on the stage, the column must remain visible (else the
        applicant disappears)."""
        global_stage = self._create_stage(
            'JSC kfg occupied', sequence=40)
        applicant = self._create_applicant('JSC r10 applicant', self.job_a, global_stage)
        self.Config.create({
            'job_id': self.job_a.id,
            'stage_id': global_stage.id,
            'visible': False,
        })
        # Simulating the kanban group_expand: stages argument carries the
        # currently-grouped stages (= those used by applicants).
        stages_a = self.Applicant.with_context(
            default_job_id=self.job_a.id,
        )._read_group_stage_ids(global_stage, [], 'sequence')
        self.assertIn(global_stage, stages_a,
            "applicant-hosting stage must remain visible despite hide flag")
        self.assertEqual(applicant.stage_id, global_stage)

    def test_general_kanban_shows_only_global_stages(self):
        """Without default_job_id context (e.g. cross-job recruitment kanban),
        only global stages appear — same as stock."""
        gl = self._create_stage('JSC kfg gen-global', sequence=50)
        spec = self._create_stage(
            'JSC kfg gen-specific', sequence=60, job_ids=[self.job_a])
        stages = self.Applicant._read_group_stage_ids(
            self.Stage.browse(), [], 'sequence')
        self.assertIn(gl, stages)
        self.assertNotIn(spec, stages)

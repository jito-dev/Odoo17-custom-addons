# -*- coding: utf-8 -*-
"""Stage write/create overrides must auto-create config rows for newly-added jobs.

This is the foundation guarantee that lets downstream modules
(hr_recruitment_test_task, iq_tests_survey) simply write
`stage.job_ids = [(4, job.id)]` and trust that the stage will be visible
in the job's kanban — without each module reimplementing
hr.job.stage.config row creation.
"""
from .common import StageConfigTestCommon


class TestStageWriteCreatesConfig(StageConfigTestCommon):
    def test_write_job_ids_creates_config_row(self):
        """The classic add_test_task / add_iq_test path: a downstream
        module writes job_ids directly, and the foundation creates the
        config row with visible=True so the stage shows up in kanban."""
        stage = self._create_stage('JSC write-add stage')
        # Sanity: created as global, no rows for our job
        self.assertEqual(stage.scope, 'global')
        self.assertFalse(self.Config.search([
            ('job_id', '=', self.job_a.id),
            ('stage_id', '=', stage.id),
        ]))

        stage.write({'job_ids': [(4, self.job_a.id)]})

        config = self.Config.search([
            ('job_id', '=', self.job_a.id),
            ('stage_id', '=', stage.id),
        ])
        self.assertEqual(len(config), 1,
            "write to job_ids must create exactly one config row")
        self.assertTrue(config.visible,
            "auto-created config row must default to visible=True so the "
            "stage shows up in the kanban immediately")
        self.assertEqual(config.sequence, stage.sequence)

    def test_write_job_ids_idempotent(self):
        """Re-writing the same (4, id) command must not create duplicate rows."""
        stage = self._create_stage('JSC idempotent stage')
        stage.write({'job_ids': [(4, self.job_a.id)]})
        stage.write({'job_ids': [(4, self.job_a.id)]})

        rows = self.Config.search([
            ('job_id', '=', self.job_a.id),
            ('stage_id', '=', stage.id),
        ])
        self.assertEqual(len(rows), 1)

    def test_write_job_ids_preserves_manual_hidden(self):
        """A recruiter who manually flips config.visible=False must not be
        overridden when a write to job_ids re-fires the auto-create logic.
        """
        stage = self._create_stage('JSC preserve-hidden stage')
        stage.write({'job_ids': [(4, self.job_a.id)]})
        config = self.Config.search([
            ('job_id', '=', self.job_a.id),
            ('stage_id', '=', stage.id),
        ])
        config.visible = False
        # Some other write to job_ids — must not flip visible back to True
        stage.write({'job_ids': [(4, self.job_b.id)]})

        self.assertFalse(config.visible,
            "auto-create must skip rows that already exist (idempotent), "
            "preserving any manual visible=False set by the recruiter")

    def test_write_remove_job_does_not_delete_config(self):
        """Removing a job from job_ids must NOT delete its config row —
        an applicant might still be on that (job, stage) and would
        disappear from the kanban (R10)."""
        stage = self._create_stage('JSC remove-keep stage')
        stage.write({'job_ids': [(4, self.job_a.id)]})
        stage.write({'job_ids': [(3, self.job_a.id)]})

        config = self.Config.search([
            ('job_id', '=', self.job_a.id),
            ('stage_id', '=', stage.id),
        ])
        self.assertTrue(config,
            "config row must survive job_ids removal so applicants "
            "already on the stage remain reachable")

    def test_create_stage_with_job_ids_creates_config_row(self):
        """When a new stage is created with job_ids set in vals (not via
        the scope inverse), the create override must also produce a
        config row."""
        stage = self.Stage.create({
            'name': 'JSC born-specific stage',
            'sequence': 42,
            'job_ids': [(6, 0, [self.job_a.id])],
        })

        config = self.Config.search([
            ('job_id', '=', self.job_a.id),
            ('stage_id', '=', stage.id),
        ])
        self.assertEqual(len(config), 1)
        self.assertTrue(config.visible)
        self.assertEqual(config.sequence, 42)

    def test_write_multi_command_6_creates_rows_for_all(self):
        """The (6, 0, [ids]) replacement command must also trigger
        auto-create for every newly-listed job."""
        stage = self._create_stage('JSC multi-add stage')
        stage.write({'job_ids': [(6, 0, [self.job_a.id, self.job_b.id])]})

        rows = self.Config.search([
            ('job_id', 'in', [self.job_a.id, self.job_b.id]),
            ('stage_id', '=', stage.id),
        ])
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r.visible for r in rows))

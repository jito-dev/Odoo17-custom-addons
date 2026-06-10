# -*- coding: utf-8 -*-
"""Tests for v17.0.1.0.1 auto-population behaviour.

A new job auto-creates config rows for every existing global stage.
A new global stage auto-creates config rows for every existing job.
Default visibility follows ``stage.default_visible_in_new_jobs``.
"""
from .common import StageConfigTestCommon


class TestAutoPopulation(StageConfigTestCommon):

    def test_new_job_gets_rows_for_all_global_stages(self):
        global_stages = self.Stage.search([('job_ids', '=', False)])
        new_job = self.Job.create({
            'name': 'Mobile Engineer JSC',
            'department_id': self.dept.id,
        })
        configs = self.Config.search([('job_id', '=', new_job.id)])
        self.assertEqual(
            set(configs.stage_id.ids),
            set(global_stages.ids),
            'New job must have a config row for every existing global stage.')

    def test_new_global_stage_gets_rows_for_all_jobs(self):
        jobs = self.Job.search([])
        stage = self._create_stage('Auto Backfill Stage JSC', sequence=99)
        configs = self.Config.search([('stage_id', '=', stage.id)])
        self.assertEqual(
            set(configs.job_id.ids),
            set(jobs.ids),
            'New global stage must seed config rows for every existing job.')
        # default_visible_in_new_jobs defaults to False → rows start hidden
        self.assertTrue(all(c.visible is False for c in configs),
                        'Non-whitelist stages default to hidden.')

    def test_default_visible_flag_propagates(self):
        stage = self._create_stage('Visible Default JSC')
        stage.default_visible_in_new_jobs = True
        new_job = self.Job.create({
            'name': 'DevOps Engineer JSC',
            'department_id': self.dept.id,
        })
        config = self.Config.search([
            ('job_id', '=', new_job.id),
            ('stage_id', '=', stage.id),
        ])
        self.assertTrue(config.visible,
                        'default_visible_in_new_jobs=True must propagate.')

    def test_sync_is_idempotent(self):
        before = self.Config.search_count([('job_id', '=', self.job_a.id)])
        self.job_a._sync_stage_configs()
        after = self.Config.search_count([('job_id', '=', self.job_a.id)])
        self.assertEqual(before, after,
                         'Sync must not duplicate existing rows.')

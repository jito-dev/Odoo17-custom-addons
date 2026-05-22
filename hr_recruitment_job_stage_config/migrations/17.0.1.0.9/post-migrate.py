# -*- coding: utf-8 -*-
"""Post-migrate for 17.0.1.0.9.

Backfill missing hr.job.stage.config rows for (existing job, global stage)
pairs.

`hr.job.create()` materialises config rows for all global stages when a
NEW job is created, and `hr.recruitment.stage.create()` materialises
rows on every existing job when a NEW global stage is created. But for
databases where:

  - jobs were created BEFORE the module was installed, or
  - jobs were imported through a path that bypassed the create hook
    (e.g. data-files, ORM with no_call=True wrappers),

the resulting (job, global-stage) edges have no config row. Without a
row, the job-form Stages tab cannot list the stage, so the recruiter
cannot toggle its `visible` flag. The previous migrations
(17.0.1.0.1, 17.0.1.0.3) covered slightly different gaps; this one is
the catch-all that re-runs `_sync_stage_configs()` on every existing
job. It is idempotent — `_sync_stage_configs` skips any (job, stage)
pair that already has a row.

Additive only: never modifies an existing config row, never touches
applicant.stage_id. Re-running creates zero rows.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    Job = env['hr.job'].sudo()
    Config = env['hr.job.stage.config'].sudo()

    before = Config.search_count([])
    jobs = Job.search([])
    jobs._sync_stage_configs()
    after = Config.search_count([])

    _logger.info(
        '[hr_recruitment_job_stage_config 17.0.1.0.9] '
        'Sync backfill across %d jobs created %d new config rows '
        '(was %d → %d).',
        len(jobs), after - before, before, after)

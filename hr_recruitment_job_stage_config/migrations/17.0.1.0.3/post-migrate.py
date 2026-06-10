# -*- coding: utf-8 -*-
"""Post-migrate for 17.0.1.0.3.

Backfill missing hr.job.stage.config rows for every (job, stage) pair
where `stage.job_ids` already lists the job but no config row exists.

Before this version, downstream modules (hr_recruitment_test_task,
iq_tests_survey) wrote stage.job_ids directly and the inverse on
`scope` did not fire — leaving the (job, stage) edge without a config
row. The kanban filter in hr.applicant._read_group_stage_ids treats a
scope='specific' stage without a config row as HIDDEN. Result: stages
added by add_test_task / add_iq_test were silently invisible.

The fix in v17.0.1.0.3 auto-creates the row on stage.write/create. This
migration covers existing databases where the rows are missing.

Additive only: never modifies an existing config row, never touches
applicant.stage_id. Re-running creates zero rows.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    Stage = env['hr.recruitment.stage'].sudo()
    Config = env['hr.job.stage.config'].sudo()

    specific_stages = Stage.search([('job_ids', '!=', False)])

    created = 0
    pairs_per_job = {}
    for stage in specific_stages:
        for job in stage.job_ids:
            exists = Config.search_count([
                ('job_id', '=', job.id),
                ('stage_id', '=', stage.id),
            ])
            if exists:
                continue
            Config.create({
                'job_id': job.id,
                'stage_id': stage.id,
                'sequence': stage.sequence,
            })
            created += 1
            pairs_per_job.setdefault(job.id, []).append(stage.id)

    _logger.info(
        '[hr_recruitment_job_stage_config 17.0.1.0.3] '
        'Backfilled %d missing (job, specific-stage) config rows. '
        'Jobs touched: %s',
        created, sorted(pairs_per_job.keys()))

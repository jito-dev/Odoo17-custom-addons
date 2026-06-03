# -*- coding: utf-8 -*-
"""Post-migrate for 17.0.1.0.1.

Two additive tweaks — never changes existing config-row visibility:

1. Seed ``default_visible_in_new_jobs=True`` for the canonical workflow
   stages (New / Initial Qualification / First Interview / Second
   Interview / Contract Proposal). Everything else stays False so future
   new jobs only auto-show the curated workflow.

2. Backfill any (job × global-stage) pair that is missing a config row
   so the redesigned Stages tab shows the complete catalogue on existing
   databases. Newly created rows take ``visible`` from the stage's
   ``default_visible_in_new_jobs`` flag, except when an applicant is
   already on that (job, stage) — in that case we force visible=True
   so the user does not lose track of in-flight candidates.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

DEFAULT_VISIBLE_NAMES = (
    'New',
    'Initial Qualification',
    'First Interview',
    'Second Interview',
    'Contract Proposal',
)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    # 1. Seed default_visible_in_new_jobs
    Stage = env['hr.recruitment.stage'].sudo()
    whitelist = Stage.search([('name', 'in', list(DEFAULT_VISIBLE_NAMES))])
    if whitelist:
        whitelist.write({'default_visible_in_new_jobs': True})
    _logger.info(
        '[hr_recruitment_job_stage_config 17.0.1.0.1] '
        'Marked %d canonical stages as default-visible: %s',
        len(whitelist), whitelist.mapped('name'))

    # 2. Backfill missing (job, global-stage) config rows
    Config = env['hr.job.stage.config'].sudo()
    Job = env['hr.job'].sudo()
    Applicant = env['hr.applicant'].sudo()
    global_stages = Stage.search([('job_ids', '=', False)])
    jobs = Job.search([])

    created = 0
    for job in jobs:
        existing_stage_ids = set(job.stage_config_ids.stage_id.ids)
        for stage in global_stages:
            if stage.id in existing_stage_ids:
                continue
            has_applicants = bool(Applicant.with_context(
                active_test=False).search_count([
                ('job_id', '=', job.id),
                ('stage_id', '=', stage.id),
            ]))
            Config.create({
                'job_id': job.id,
                'stage_id': stage.id,
                'sequence': stage.sequence,
                'visible': has_applicants or stage.default_visible_in_new_jobs,
            })
            created += 1
    _logger.info(
        '[hr_recruitment_job_stage_config 17.0.1.0.1] '
        'Backfilled %d missing config rows.', created)

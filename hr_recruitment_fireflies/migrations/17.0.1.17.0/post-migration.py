# -*- coding: utf-8 -*-
"""Split the legacy ``interview_question_template`` Text (one question per line)
into ordered ``hr.job.stage.question`` rows.

Up to 17.0.1.16.x the per-(job, stage) default interview questions were stored
as a single Text field, one question per line. From 17.0.1.17.0 they are an
ordered one2many drag-list. This migration converts each non-empty, de-duplicated
line into a row, preserving order. The legacy column is left in place (dormant)
so no data is lost and the change stays reversible.

Idempotent: a config that already has question rows is skipped, so re-running
the migration never doubles the list.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Config = env['hr.job.stage.config']
    if 'interview_question_template' not in Config._fields:
        return

    configs = Config.search([('interview_question_template', '!=', False)])
    Question = env['hr.job.stage.question']
    migrated_rows = 0
    migrated_configs = 0
    for config in configs:
        if config.interview_question_ids:
            # Already converted (or the row set was populated by hand) — never
            # duplicate.
            continue
        seen = set()
        seq = 0
        vals_list = []
        for raw in (config.interview_question_template or '').splitlines():
            q = raw.strip()
            if not q or q.lower() in seen:
                continue
            seen.add(q.lower())
            seq += 10
            vals_list.append({
                'config_id': config.id,
                'sequence': seq,
                'name': q,
            })
        if vals_list:
            Question.create(vals_list)
            migrated_rows += len(vals_list)
            migrated_configs += 1

    _logger.info(
        "hr_recruitment_fireflies: migrated %s question line(s) across %s "
        "stage config(s) into hr.job.stage.question rows.",
        migrated_rows, migrated_configs,
    )

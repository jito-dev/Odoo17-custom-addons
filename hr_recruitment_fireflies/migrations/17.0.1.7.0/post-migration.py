# -*- coding: utf-8 -*-
"""Carry over any free-text custom questions into question rows.

Up to 17.0.1.6.0 the recruiter typed ad-hoc questions into the free-text
`custom_questions` field, and answering rebuilt `custom_qa_line_ids`. From
17.0.1.7.0 the questions ARE the rows. For interviews that had typed questions
but never got answered (no custom rows yet), we recreate them as rows so nothing
the recruiter wrote is lost. Interviews that already have custom rows are left
untouched (their rows already reflect the questions).
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # The obsolete column is still present at post-migration time.
    cr.execute(
        """
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'hr_applicant_interview'
          AND column_name = 'custom_questions'
        """
    )
    if not cr.fetchone():
        return

    cr.execute(
        """
        SELECT i.id, i.custom_questions
        FROM hr_applicant_interview i
        WHERE i.custom_questions IS NOT NULL
          AND btrim(i.custom_questions) <> ''
          AND NOT EXISTS (
              SELECT 1 FROM hr_applicant_interview_qa q
              WHERE q.interview_id = i.id AND q.is_custom = TRUE
          )
        """
    )
    rows = cr.fetchall()
    if not rows:
        return

    env = api.Environment(cr, SUPERUSER_ID, {})
    Qa = env['hr.applicant.interview.qa']
    created = 0
    for interview_id, text in rows:
        seq = 10
        for line in (text or '').splitlines():
            line = line.strip()
            if not line:
                continue
            Qa.create({
                'interview_id': interview_id,
                'sequence': seq,
                'is_custom': True,
                'question': line,
                'coverage': 'not_asked',
            })
            seq += 10
            created += 1
    _logger.info(
        "hr_recruitment_fireflies: migrated %s free-text question(s) into rows.",
        created,
    )

# -*- coding: utf-8 -*-
"""Drop the legacy template-driven Q&A lines.

Up to 17.0.1.6.0 the module kept a separate template-driven Q&A table
(is_custom = False), populated from the job's question template. That table is
removed in 17.0.1.7.0 (the JD-derived role context feeds the summary instead),
so its rows are deleted here. Recruiter questions (is_custom = True) are kept.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute(
        "DELETE FROM hr_applicant_interview_qa WHERE is_custom = FALSE"
    )
    _logger.info(
        "hr_recruitment_fireflies: removed %s legacy template Q&A line(s).",
        cr.rowcount,
    )

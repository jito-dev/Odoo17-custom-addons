# -*- coding: utf-8 -*-
from odoo import fields, models


class HrJobStageConfig(models.Model):
    """Per-(job, stage) default interview questions.

    Declared here (not in hr_recruitment_job_stage_config) because the feature
    belongs to the Fireflies module; the field *name* is reserved in that
    module's ``_PAYLOAD_FIELDS`` tuple so the stage scope-flip cleanup counts
    these questions as payload and never drops a config row that only holds
    them. One question per line; seeded verbatim into a new interview's
    recruiter questions (``hr.applicant.interview.custom_qa_line_ids``).
    """
    _inherit = 'hr.job.stage.config'

    interview_question_template = fields.Text(
        string="Default Interview Questions",
        help="One question per line. When a Fireflies interview is created for "
             "a candidate sitting on this (job, stage), these questions are "
             "copied into the interview's own questions so the recruiter only "
             "clicks Ask AI. The recruiter can still add or remove questions "
             "on the interview; changing this template does not touch existing "
             "interviews.",
    )

    def _fireflies_question_lines(self):
        """Return the template as a de-duplicated, order-preserving list of
        non-empty question strings."""
        self.ensure_one()
        seen = set()
        lines = []
        for raw in (self.interview_question_template or '').splitlines():
            q = raw.strip()
            if not q:
                continue
            key = q.lower()
            if key in seen:
                continue
            seen.add(key)
            lines.append(q)
        return lines

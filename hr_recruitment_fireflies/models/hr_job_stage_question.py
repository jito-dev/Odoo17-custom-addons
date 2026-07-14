# -*- coding: utf-8 -*-
from odoo import fields, models


class HrJobStageQuestion(models.Model):
    """One default interview question for a (job, stage).

    The ordered set of these rows is the per-stage question template: when a
    Fireflies interview is created for a candidate sitting on this (job, stage),
    the questions are copied verbatim into the interview's own recruiter
    questions (``hr.applicant.interview.custom_qa_line_ids``). Editing the set
    later never touches interviews already created.

    Replaces the former ``interview_question_template`` Text field (one question
    per line): the drag-list gives explicit ordering and inline editing while
    keeping the exact same downstream contract via
    ``hr.job.stage.config._fireflies_question_lines``.
    """
    _name = 'hr.job.stage.question'
    _description = 'Default Interview Question for a Job Stage'
    _order = 'sequence, id'

    config_id = fields.Many2one(
        'hr.job.stage.config',
        string="Stage configuration",
        required=True,
        ondelete='cascade',
        index=True,
    )
    sequence = fields.Integer(string="Sequence", default=10, index=True)
    name = fields.Char(string="Question", required=True)

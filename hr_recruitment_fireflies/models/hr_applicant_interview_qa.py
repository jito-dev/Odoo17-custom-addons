# -*- coding: utf-8 -*-
from odoo import fields, models


class HrApplicantInterviewQa(models.Model):
    """One Q&A line of an interview summary: an interview question and the
    AI-paraphrased answer the candidate gave, plus how well it was covered."""
    _name = 'hr.applicant.interview.qa'
    _description = 'Interview Q&A Line'
    _order = 'sequence, id'

    interview_id = fields.Many2one(
        'hr.applicant.interview',
        string="Interview",
        required=True,
        ondelete='cascade',
        index=True,
    )
    sequence = fields.Integer(string="Sequence", default=10)
    is_custom = fields.Boolean(
        string="Custom",
        default=True,
        help="Recruiter's own question, answered from the saved transcript. Kept "
             "intact across re-analyses of the client summary.",
    )
    question = fields.Char(string="Question", required=True)
    answer = fields.Text(string="Candidate's Answer")
    coverage = fields.Selection(
        selection=[
            ('covered', 'Covered'),
            ('partial', 'Partially Covered'),
            ('missed', 'Not Answered'),
            ('not_asked', 'Not Asked'),
        ],
        string="Coverage",
        default='not_asked',
    )

# -*- coding: utf-8 -*-

from odoo import api, fields, models

class HrJobQuestionLine(models.Model):
    _name = 'hr.job.question.line'
    _description = 'Job Form Question Line'
    _order = 'sequence, id'

    job_id = fields.Many2one(
        comodel_name='hr.job',
        string='Job',
        required=True,
        ondelete='cascade',
        index=True,
    )
    question_id = fields.Many2one(
        comodel_name='hr.form.question',
        string='Question',
        required=True,
        ondelete='cascade',
        index=True,
    )
    sequence = fields.Integer(
        string='Sequence',
        default=10,
    )

    # Related fields for UI display
    title = fields.Char(
        related='question_id.title',
        readonly=True,
    )
    question_type = fields.Selection(
        related='question_id.question_type',
        readonly=True,
    )
    is_required = fields.Boolean(
        related='question_id.is_required',
        readonly=True,
    )
    is_section = fields.Boolean(
        related='question_id.is_section',
        readonly=True,
    )

    def unlink(self):
        """
        Cleanup: If the question was specific to this job (Custom), 
        delete the question itself when the line is removed.
        Shared/Template questions are preserved.
        """
        questions_to_delete = self.env['hr.form.question']
        for line in self:
            # If the question belongs to this job (custom), mark it for deletion
            if line.question_id.job_id == line.job_id:
                questions_to_delete |= line.question_id
        
        res = super().unlink()
        
        if questions_to_delete:
            questions_to_delete.unlink()
            
        return res
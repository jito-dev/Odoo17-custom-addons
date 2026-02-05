# -*- coding: utf-8 -*-

from odoo import api, fields, models, Command, _


class HrJob(models.Model):
    _inherit = 'hr.job'

    # Form configuration
    use_forms = fields.Boolean(
        string='Use Forms',
        default=False,
        help='Enable custom application forms for this job',
    )
    
    # Standard Form Configuration
    form_show_phone = fields.Boolean(string='Show Phone', default=True)
    form_show_linkedin = fields.Boolean(string='Show LinkedIn', default=True)
    form_show_resume = fields.Boolean(string='Show Resume Upload', default=True)
    form_show_intro = fields.Boolean(string='Show Short Introduction', default=True)

    form_template_id = fields.Many2one(
        comodel_name='hr.form.template',
        string='Form Template',
        help='Select a form template to load its questions.',
    )
    
    # Unified Question List
    question_line_ids = fields.One2many(
        comodel_name='hr.job.question.line',
        inverse_name='job_id',
        string='Form Questions',
        copy=True,
    )
    
    # Keep constraint/inverse relation, but hide from view
    form_question_ids = fields.One2many(
        comodel_name='hr.form.question',
        inverse_name='job_id',
        string='Job Specific Questions (Data)',
        readonly=True,
    )

    form_question_count = fields.Integer(
        string='Form Question Count',
        compute='_compute_form_question_count',
    )

    @api.depends('question_line_ids')
    def _compute_form_question_count(self):
        for job in self:
            questions = job.question_line_ids.mapped('question_id')
            job.form_question_count = len(
                questions.filtered(lambda q: not q.is_section)
            )

    @api.onchange('use_forms')
    def _onchange_use_forms(self):
        """Clear form settings when disabling forms."""
        if not self.use_forms:
            self.form_template_id = False
            self.question_line_ids = [Command.clear()]

    @api.onchange('form_template_id')
    def _onchange_form_template_id(self):
        """Load template questions into the unified list without removing existing ones."""
        if self.form_template_id:
            # FIX: We do NOT clear existing questions ([Command.clear()])
            # so custom questions are preserved.
            
            # Get IDs of questions already on the job to prevent duplicates
            existing_q_ids = self.question_line_ids.mapped('question_id').ids
            
            new_lines = []
            for q in self.form_template_id.question_ids:
                if q.id not in existing_q_ids:
                    new_lines.append(Command.create({
                        'question_id': q.id,
                        'sequence': q.sequence,
                    }))
            
            # Append new lines to the existing list
            if new_lines:
                self.question_line_ids = new_lines

    def get_form_questions(self):
        """
        Get all questions applicable to this job in the specific order
        defined in the unified line list.
        """
        self.ensure_one()
        # Returns recordset of questions sorted by the line sequence
        return self.question_line_ids.sorted('sequence').mapped('question_id')

    def action_view_form_questions(self):
        """Open form questions in a separate view."""
        self.ensure_one()
        # We need to show questions linked via lines
        question_ids = self.question_line_ids.mapped('question_id').ids
        return {
            'type': 'ir.actions.act_window',
            'name': 'Form Questions',
            'res_model': 'hr.form.question',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', question_ids)],
            'context': {
                'default_job_id': self.id,
                'default_is_section': False,
            },
        }

    def action_add_questions_from_template(self):
        """Open wizard to add questions from templates."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Add Questions from Template',
            'res_model': 'hr.form.add.questions.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_job_id': self.id,
            },
        }
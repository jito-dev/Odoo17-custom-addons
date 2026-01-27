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
        help='Select a form template to add questions. New questions will be appended to existing ones.',
    )
    
    # Unified question field
    form_question_ids = fields.One2many(
        comodel_name='hr.form.question',
        inverse_name='job_id',
        string='Questions',
        help='Questions specific to this job',
    )

    form_question_count = fields.Integer(
        string='Form Question Count',
        compute='_compute_form_question_count',
    )

    @api.depends('form_question_ids')
    def _compute_form_question_count(self):
        for job in self:
            job.form_question_count = len(
                job.form_question_ids.filtered(lambda q: not q.is_section)
            )

    @api.onchange('use_forms')
    def _onchange_use_forms(self):
        """Clear form settings when disabling forms."""
        if not self.use_forms:
            self.form_template_id = False

    @api.onchange('form_template_id')
    def _onchange_form_template_id(self):
        """Append questions from template when selected."""
        if not self.form_template_id:
            return

        # STRICT DUPLICATE CHECK
        # Normalize titles to lowercase and stripped for comparison
        existing_titles = set()
        for q in self.form_question_ids:
            if q.title:
                existing_titles.add(q.title.strip().lower())
        
        # Calculate start sequence
        current_max_seq = 0
        if self.form_question_ids:
            current_max_seq = max(self.form_question_ids.mapped('sequence') or [0])

        new_commands = []
        for i, question in enumerate(self.form_template_id.question_ids):
            # Skip if title exists (case-insensitive check)
            q_title_norm = question.title.strip().lower() if question.title else ''
            if q_title_norm in existing_titles:
                 continue
            
            # Add to local set so we don't add duplicate from template itself if any
            existing_titles.add(q_title_norm)

            # Prepare values for copy
            vals = {
                'title': question.title,
                'description': question.description,
                'sequence': current_max_seq + 10 + (i * 10), # Ensure valid sequence
                'is_section': question.is_section,
                'question_type': question.question_type,
                'is_required': question.is_required,
                'placeholder': question.placeholder,
                'validation_min': question.validation_min,
                'validation_max': question.validation_max,
                'validation_error_msg': question.validation_error_msg,
                'rating_min': question.rating_min,
                'rating_max': question.rating_max,
                'rating_min_label': question.rating_min_label,
                'rating_max_label': question.rating_max_label,
            }
            
            # Answer options
            if question.answer_option_ids:
                vals['answer_option_ids'] = [
                    Command.create({'value': opt.value, 'sequence': opt.sequence})
                    for opt in question.answer_option_ids
                ]

            new_commands.append(Command.create(vals))

        if new_commands:
            lines = self.form_question_ids
            for cmd in new_commands:
                vals = cmd[2]
                lines += self.env['hr.form.question'].new(vals)
            self.form_question_ids = lines

    def action_view_form_questions(self):
        """Open form questions in a separate view."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Form Questions',
            'res_model': 'hr.form.question',
            'view_mode': 'tree,form',
            'domain': [('job_id', '=', self.id)],
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
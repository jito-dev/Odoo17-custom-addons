# -*- coding: utf-8 -*-

from odoo import api, fields, models


class HrFormAddQuestionsWizard(models.TransientModel):
    _name = 'hr.form.add.questions.wizard'
    _description = 'Add Questions from Template Wizard'

    job_id = fields.Many2one(
        comodel_name='hr.job',
        string='Job Position',
        required=True,
    )
    template_ids = fields.Many2many(
        comodel_name='hr.form.template',
        string='Templates',
        help='Select templates to choose questions from',
    )
    question_line_ids = fields.One2many(
        comodel_name='hr.form.add.questions.wizard.line',
        inverse_name='wizard_id',
        string='Questions',
    )

    @api.onchange('template_ids')
    def _onchange_template_ids(self):
        """Populate question lines when templates are selected."""
        # This works in the UI but data isn't persisted until saved
        if self.template_ids:
            lines = []
            for template in self.template_ids:
                for question in template.question_ids:
                    lines.append((0, 0, {
                        'template_id': template.id,
                        'question_id': question.id,
                        'selected': False,
                    }))
            self.question_line_ids = lines
        else:
            self.question_line_ids = [(5, 0, 0)]

    def action_add_questions(self):
        """Copy selected questions to the job."""
        self.ensure_one()

        # Iterate over lines and check selected
        selected_lines = self.question_line_ids.filtered(lambda l: l.selected)
        
        if not selected_lines:
            return {
                'type': 'ir.actions.client',
                'tag': 'reload',
            }

        # Get current max sequence
        existing_questions = self.job_id.form_question_ids
        max_sequence = max(existing_questions.mapped('sequence') or [0])

        # Copy selected questions
        for line in selected_lines:
            if line.question_id:
                max_sequence += 10
                new_question = line.question_id.copy_to_job(self.job_id.id)
                new_question.sequence = max_sequence

        # Reload the view to show the new questions
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }


class HrFormAddQuestionsWizardLine(models.TransientModel):
    _name = 'hr.form.add.questions.wizard.line'
    _description = 'Add Questions Wizard Line'
    _order = 'template_id, sequence'

    wizard_id = fields.Many2one(
        comodel_name='hr.form.add.questions.wizard',
        string='Wizard',
        required=True,
        ondelete='cascade',
    )
    template_id = fields.Many2one(
        comodel_name='hr.form.template',
        string='Template',
        readonly=True,
    )
    question_id = fields.Many2one(
        comodel_name='hr.form.question',
        string='Question',
        readonly=True,
    )
    selected = fields.Boolean(
        string='Select',
        default=False,
    )

    # Related fields for display
    title = fields.Char(
        string='Question Title',
        related='question_id.title',
        readonly=True,
    )
    question_type = fields.Selection(
        related='question_id.question_type',
        readonly=True,
    )
    is_section = fields.Boolean(
        related='question_id.is_section',
        readonly=True,
    )
    sequence = fields.Integer(
        related='question_id.sequence',
        readonly=True,
    )
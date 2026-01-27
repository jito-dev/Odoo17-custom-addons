# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class HrFormQuestion(models.Model):
    _name = 'hr.form.question'
    _description = 'HR Form Question'
    _order = 'sequence, id'

    # Parent reference - either template or job, not both
    template_id = fields.Many2one(
        comodel_name='hr.form.template',
        string='Form Template',
        ondelete='cascade',
        index=True,
    )
    job_id = fields.Many2one(
        comodel_name='hr.job',
        string='Job Position',
        ondelete='cascade',
        index=True,
    )

    # Question content
    title = fields.Char(
        string='Question',
        required=True,
        translate=True,
    )
    description = fields.Html(
        string='Description',
        translate=True,
        help='Additional instructions or context for this question',
    )
    sequence = fields.Integer(
        string='Sequence',
        default=10,
    )

    # Section support
    is_section = fields.Boolean(
        string='Is Section',
        default=False,
        help='If checked, this is a section header, not a question',
    )
    section_id = fields.Many2one(
        comodel_name='hr.form.question',
        string='Section',
        compute='_compute_section_id',
        store=True,
    )

    # Question type and validation - NO FILE OPTION
    question_type = fields.Selection(
        selection=[
            ('text', 'Short Text'),
            ('textarea', 'Long Text'),
            ('number', 'Number'),
            ('date', 'Date'),
            ('single_choice', 'Single Choice'),
            ('multiple_choice', 'Multiple Choice'),
            ('yes_no', 'Yes/No'),
            ('rating', 'Rating'),
        ],
        string='Question Type',
        default='text',
    )
    is_required = fields.Boolean(
        string='Required',
        default=False,
    )
    placeholder = fields.Char(
        string='Placeholder',
        translate=True,
    )

    # Answer options for choice questions
    answer_option_ids = fields.One2many(
        comodel_name='hr.form.answer.option',
        inverse_name='question_id',
        string='Answer Options',
        copy=True,
    )

    # Validation fields
    validation_min = fields.Float(
        string='Minimum Value',
        help='Minimum allowed value for number questions',
    )
    validation_max = fields.Float(
        string='Maximum Value',
        help='Maximum allowed value for number questions',
    )
    validation_error_msg = fields.Char(
        string='Validation Error Message',
        translate=True,
    )

    # Rating specific
    rating_min = fields.Integer(
        string='Rating Min',
        default=1,
    )
    rating_max = fields.Integer(
        string='Rating Max',
        default=5,
    )
    rating_min_label = fields.Char(
        string='Min Label',
        translate=True,
    )
    rating_max_label = fields.Char(
        string='Max Label',
        translate=True,
    )

    # Computed fields
    has_answer_options = fields.Boolean(
        string='Has Answer Options',
        compute='_compute_has_answer_options',
    )
    answers_validation_error = fields.Char(
        string='Validation Error',
        compute='_compute_answers_validation_error',
    )

    @api.depends('question_type')
    def _compute_has_answer_options(self):
        for question in self:
            question.has_answer_options = question.question_type in (
                'single_choice', 'multiple_choice'
            )

    @api.depends('question_type', 'answer_option_ids')
    def _compute_answers_validation_error(self):
        for question in self:
            error = False
            if question.has_answer_options and len(question.answer_option_ids) < 2:
                error = _("Choice questions must have at least 2 options")
            question.answers_validation_error = error

    @api.depends('sequence', 'template_id', 'job_id')
    def _compute_section_id(self):
        """Find the section this question belongs to."""
        for question in self:
            if question.is_section:
                question.section_id = False
                continue

            # Find nearest section with lower sequence
            domain = [
                ('is_section', '=', True),
                ('sequence', '<', question.sequence),
            ]
            if question.template_id:
                domain.append(('template_id', '=', question.template_id.id))
            elif question.job_id:
                domain.append(('job_id', '=', question.job_id.id))
            else:
                question.section_id = False
                continue

            section = self.search(domain, order='sequence desc', limit=1)
            question.section_id = section

    @api.constrains('template_id', 'job_id')
    def _check_parent(self):
        """Question must belong to either template or job, not both."""
        for question in self:
            if question.template_id and question.job_id:
                raise ValidationError(
                    _("A question cannot belong to both a template and a job.")
                )

    @api.constrains('rating_min', 'rating_max')
    def _check_rating_range(self):
        """Rating min must be less than max."""
        for question in self:
            if question.question_type == 'rating':
                if question.rating_min >= question.rating_max:
                    raise ValidationError(
                        _("Rating minimum must be less than maximum.")
                    )

    @api.onchange('question_type')
    def _onchange_question_type(self):
        """Clear irrelevant fields when changing question type."""
        if not self.has_answer_options:
            self.answer_option_ids = [(5, 0, 0)]  # Clear options
        if self.question_type != 'rating':
            self.rating_min = 1
            self.rating_max = 5
            self.rating_min_label = False
            self.rating_max_label = False
        if self.question_type != 'number':
            self.validation_min = 0
            self.validation_max = 0
            self.validation_error_msg = False

    def copy_to_job(self, job_id):
        """Copy this question to a job's custom questions."""
        self.ensure_one()
        vals = {
            'template_id': False,
            'job_id': job_id,
            'title': self.title,
            'description': self.description,
            'sequence': self.sequence,
            'is_section': self.is_section,
            'question_type': self.question_type,
            'is_required': self.is_required,
            'placeholder': self.placeholder,
            'validation_min': self.validation_min,
            'validation_max': self.validation_max,
            'validation_error_msg': self.validation_error_msg,
            'rating_min': self.rating_min,
            'rating_max': self.rating_max,
            'rating_min_label': self.rating_min_label,
            'rating_max_label': self.rating_max_label,
        }
        new_question = self.create(vals)

        # Copy answer options
        for option in self.answer_option_ids:
            option.copy({'question_id': new_question.id})

        return new_question
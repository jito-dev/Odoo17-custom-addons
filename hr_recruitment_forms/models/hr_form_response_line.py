# -*- coding: utf-8 -*-

from odoo import api, fields, models


class HrFormResponseLine(models.Model):
    _name = 'hr.form.response.line'
    _description = 'HR Form Response Line'
    _order = 'question_sequence, id'

    response_id = fields.Many2one(
        comodel_name='hr.form.response',
        string='Response',
        required=True,
        ondelete='cascade',
        index=True,
    )
    # Changed ondelete to set null so answers persist if question is deleted
    question_id = fields.Many2one(
        comodel_name='hr.form.question',
        string='Question',
        required=False,
        ondelete='set null', 
    )

    # Stored fields to preserve data history
    question_title = fields.Char(
        string='Question Title',
        compute='_compute_question_snapshot',
        store=True,
        readonly=False, # Allow editing title if needed
    )
    question_type = fields.Selection(
        related='question_id.question_type',
        store=True,
        readonly=False, # Allow editing if disconnected
    )
    question_sequence = fields.Integer(
        string='Sequence',
        related='question_id.sequence',
        store=True,
    )
    is_section = fields.Boolean(
        related='question_id.is_section',
        store=True,
    )
    
    applicant_id = fields.Many2one(
        comodel_name='hr.applicant',
        string='Applicant',
        related='response_id.applicant_id',
        store=True,
        index=True,
    )
    job_id = fields.Many2one(
        comodel_name='hr.job',
        string='Job Position',
        related='response_id.job_id',
        store=True,
        index=True,
    )

    # Answer value fields
    value_text = fields.Char(string='Text Answer')
    value_textarea = fields.Text(string='Long Text Answer')
    value_number = fields.Float(string='Number Answer')
    value_date = fields.Date(string='Date Answer')
    value_single_choice_id = fields.Many2one(
        comodel_name='hr.form.answer.option',
        string='Single Choice Answer',
        ondelete='set null',
    )
    value_multiple_choice_ids = fields.Many2many(
        comodel_name='hr.form.answer.option',
        relation='hr_form_response_line_option_rel',
        column1='line_id',
        column2='option_id',
        string='Multiple Choice Answer',
    )
    value_yes_no = fields.Boolean(string='Yes/No Answer')
    value_rating = fields.Integer(string='Rating Answer')
    value_file = fields.Binary(string="File Content") 
    value_filename = fields.Char(string="Filename")

    # Computed display value
    display_value = fields.Char(
        string='Answer',
        compute='_compute_display_value',
        store=True,
    )
    is_empty = fields.Boolean(
        string='Is Empty',
        compute='_compute_is_empty',
        store=True,
    )

    @api.depends('question_id')
    def _compute_question_snapshot(self):
        """Snapshot question details on creation."""
        for line in self:
            if line.question_id:
                line.question_title = line.question_id.title

    @api.depends(
        'question_type',
        'is_section',
        'value_text',
        'value_textarea',
        'value_number',
        'value_date',
        'value_single_choice_id',
        'value_multiple_choice_ids',
        'value_yes_no',
        'value_rating',
        'value_filename',
    )
    def _compute_display_value(self):
        for line in self:
            value = ''
            if line.is_section:
                value = '' 
            else:
                qtype = line.question_type
                if qtype == 'text':
                    value = line.value_text or ''
                elif qtype == 'textarea':
                    value = line.value_textarea or ''
                    if len(value) > 100:
                        value = value[:100] + '...'
                elif qtype == 'number':
                    value = str(line.value_number) if line.value_number else ''
                elif qtype == 'date':
                    value = str(line.value_date) if line.value_date else ''
                elif qtype == 'single_choice':
                    value = line.value_single_choice_id.value if line.value_single_choice_id else ''
                elif qtype == 'multiple_choice':
                    value = ', '.join(line.value_multiple_choice_ids.mapped('value'))
                elif qtype == 'yes_no':
                    value = 'Yes' if line.value_yes_no else 'No'
                elif qtype == 'rating':
                    value = str(line.value_rating) if line.value_rating else ''
                elif qtype == 'file':
                    value = line.value_filename or 'File Uploaded'

            line.display_value = value

    @api.depends(
        'question_type',
        'is_section',
        'value_text',
        'value_textarea',
        'value_number',
        'value_date',
        'value_single_choice_id',
        'value_multiple_choice_ids',
        'value_yes_no',
        'value_rating',
        'value_file',
    )
    def _compute_is_empty(self):
        for line in self:
            if line.is_section:
                line.is_empty = False
                continue

            qtype = line.question_type
            is_empty = True

            if qtype == 'text':
                is_empty = not line.value_text
            elif qtype == 'textarea':
                is_empty = not line.value_textarea
            elif qtype == 'number':
                is_empty = line.value_number == 0
            elif qtype == 'date':
                is_empty = not line.value_date
            elif qtype == 'single_choice':
                is_empty = not line.value_single_choice_id
            elif qtype == 'multiple_choice':
                is_empty = not line.value_multiple_choice_ids
            elif qtype == 'yes_no':
                is_empty = False  # Boolean always has a value
            elif qtype == 'rating':
                is_empty = not line.value_rating
            elif qtype == 'file':
                is_empty = not line.value_file

            line.is_empty = is_empty

    def get_answer_value(self):
        """Get the actual answer value based on question type."""
        self.ensure_one()
        if self.is_section:
            return None
            
        qtype = self.question_type
        if qtype == 'text':
            return self.value_text
        elif qtype == 'textarea':
            return self.value_textarea
        elif qtype == 'number':
            return self.value_number
        elif qtype == 'date':
            return self.value_date
        elif qtype == 'single_choice':
            return self.value_single_choice_id.value if self.value_single_choice_id else None
        elif qtype == 'multiple_choice':
            return self.value_multiple_choice_ids.mapped('value')
        elif qtype == 'yes_no':
            return self.value_yes_no
        elif qtype == 'rating':
            return self.value_rating
        elif qtype == 'file':
            return self.value_filename

        return None
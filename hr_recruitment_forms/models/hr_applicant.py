# -*- coding: utf-8 -*-
import logging
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.http import request

_logger = logging.getLogger(__name__)


class HrApplicant(models.Model):
    _inherit = 'hr.applicant'

    form_response_id = fields.Many2one(
        comodel_name='hr.form.response',
        string='Form Response',
        readonly=True,
        copy=False,
    )
    # Show all lines including sections
    form_response_line_ids = fields.One2many(
        comodel_name='hr.form.response.line',
        related='form_response_id.response_line_ids',
        string='Form Answers',
        readonly=False,
    )
    has_form_response = fields.Boolean(
        string='Has Form Response',
        compute='_compute_has_form_response',
    )

    @api.depends('form_response_id')
    def _compute_has_form_response(self):
        for applicant in self:
            applicant.has_form_response = bool(applicant.form_response_id)

    def action_view_form_response(self):
        self.ensure_one()
        if self.form_response_id:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'hr.form.response',
                'res_id': self.form_response_id.id,
                'view_mode': 'form',
                'target': 'current',
            }

    def _create_form_response(self, form_answers, questions):
        """Create form response from submitted answers."""
        self.ensure_one()

        # Create the response record using sudo()
        response = self.env['hr.form.response'].sudo().create({
            'applicant_id': self.id,
        })

        # Create response lines - Iterate ALL questions
        for question in questions:
            line_vals = {
                'response_id': response.id,
                'question_id': question.id,
            }

            if question.is_section:
                pass
            else:
                answer_value = form_answers.get(str(question.id))
                
                # Set value based on type
                if question.question_type == 'text':
                    line_vals['value_text'] = answer_value or ''
                elif question.question_type == 'textarea':
                    line_vals['value_textarea'] = answer_value or ''
                elif question.question_type == 'number':
                    try:
                        line_vals['value_number'] = float(answer_value) if answer_value else 0
                    except (ValueError, TypeError):
                        line_vals['value_number'] = 0
                elif question.question_type == 'date':
                    line_vals['value_date'] = answer_value or False
                elif question.question_type == 'single_choice':
                    if answer_value:
                        try:
                            # Handle potential string/list issues
                            if isinstance(answer_value, list) and len(answer_value) > 0:
                                val_to_int = answer_value[0]
                            else:
                                val_to_int = answer_value
                            
                            # Clean string if it comes as "4,5" (shouldn't for single, but safe to check)
                            if isinstance(val_to_int, str) and ',' in val_to_int:
                                val_to_int = val_to_int.split(',')[0]

                            line_vals['value_single_choice_id'] = int(val_to_int)
                        except (ValueError, TypeError):
                            pass
                elif question.question_type == 'multiple_choice':
                    if answer_value:
                        option_ids = []
                        # Handle list from request.params.getall() if adapted, or standard list
                        if isinstance(answer_value, list):
                            try:
                                option_ids = [int(v) for v in answer_value if v]
                            except (ValueError, TypeError):
                                pass
                        # Handle string "4,5" from request.params.get()
                        elif isinstance(answer_value, str):
                            try:
                                # Split by comma and convert
                                option_ids = [int(v.strip()) for v in answer_value.split(',') if v.strip()]
                            except (ValueError, TypeError):
                                pass
                        # Handle single int/value
                        else:
                            try:
                                option_ids = [int(answer_value)]
                            except (ValueError, TypeError):
                                pass
                                
                        if option_ids:
                            line_vals['value_multiple_choice_ids'] = [(6, 0, option_ids)]
                elif question.question_type == 'yes_no':
                    line_vals['value_yes_no'] = answer_value in ('yes', 'true', '1', True)
                elif question.question_type == 'rating':
                    try:
                        line_vals['value_rating'] = int(answer_value) if answer_value else 0
                    except (ValueError, TypeError):
                        line_vals['value_rating'] = 0

            self.env['hr.form.response.line'].sudo().create(line_vals)

        self.sudo().write({'form_response_id': response.id})
        return response

    @api.model_create_multi
    def create(self, vals_list):
        """Override create to handle form submissions."""
        
        # 1. EXTRACT ANSWERS FROM REQUEST.PARAMS
        form_answers = {}
        if request and request.params:
            for key, value in request.params.items():
                if key.startswith('form_q_'):
                    question_id = key.replace('form_q_', '')
                    form_answers[question_id] = value

        for vals in vals_list:
            # 2. DUPLICATE CHECK
            email = vals.get('email_from')
            job_id = vals.get('job_id')
            
            if email and job_id:
                existing_applicant = self.sudo().search([
                    ('email_from', '=ilike', email.strip()),
                    ('job_id', '=', job_id),
                    ('active', '=', True)
                ], limit=1)
                
                if existing_applicant:
                    raise ValidationError(_("You have already applied for this job position."))

            if not vals.get('name'):
                partner_name = vals.get('partner_name') or "Applicant"
                vals['name'] = f"{partner_name}'s Application"

        # 3. CREATE APPLICANTS
        applicants = super().create(vals_list)

        # 4. PROCESS FORM ANSWERS
        for applicant in applicants:
            if form_answers and applicant.job_id and applicant.job_id.use_forms:
                questions = applicant.job_id.form_question_ids.sorted('sequence')
                
                # Create Form Response and Lines
                try:
                    applicant.sudo()._create_form_response(form_answers, questions)
                except Exception as e:
                    _logger.error(f"Failed to create form response: {e}")
                    pass

        return applicants
# -*- coding: utf-8 -*-
import logging
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

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
        
        response = self.env['hr.form.response'].sudo().create({
            'applicant_id': self.id,
        })

        seq = 0
        for question in questions:
            seq += 1
            line_vals = {
                'response_id': response.id,
                'question_id': question.id,
                'question_sequence': seq,
            }

            if question.is_section:
                pass
            else:
                key = str(question.id)
                answer_value = form_answers.get(key)
                
                # Defensive: Handle lists if they sneaked past the controller
                if isinstance(answer_value, list):
                    answer_value = answer_value[0] if answer_value else ''

                if question.question_type == 'text':
                    line_vals['value_text'] = str(answer_value) if answer_value else ''
                elif question.question_type == 'textarea':
                    line_vals['value_textarea'] = str(answer_value) if answer_value else ''
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
                            val_to_int = answer_value
                            if isinstance(val_to_int, str):
                                val_to_int = val_to_int.split(',')[0]
                            line_vals['value_single_choice_id'] = int(val_to_int)
                        except (ValueError, TypeError):
                            pass
                elif question.question_type == 'multiple_choice':
                    if answer_value:
                        option_ids = []
                        if isinstance(answer_value, list):
                             pass
                        elif isinstance(answer_value, str):
                            try:
                                option_ids = [int(v.strip()) for v in answer_value.split(',') if v.strip()]
                            except (ValueError, TypeError):
                                pass
                        else:
                            try:
                                option_ids = [int(answer_value)]
                            except (ValueError, TypeError):
                                pass
                                
                        if option_ids:
                            line_vals['value_multiple_choice_ids'] = [(6, 0, option_ids)]
                elif question.question_type == 'yes_no':
                    line_vals['value_yes_no'] = str(answer_value).lower() in ('yes', 'true', '1', 'on')
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
        for vals in vals_list:
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

        return super().create(vals_list)
# -*- coding: utf-8 -*-

from odoo import api, fields, models


class HrFormResponse(models.Model):
    _name = 'hr.form.response'
    _description = 'HR Form Response'
    _order = 'create_date desc'

    applicant_id = fields.Many2one(
        comodel_name='hr.applicant',
        string='Applicant',
        required=True,
        ondelete='cascade',
        index=True,
    )
    job_id = fields.Many2one(
        comodel_name='hr.job',
        string='Job Position',
        related='applicant_id.job_id',
        store=True,
        index=True,
    )
    response_line_ids = fields.One2many(
        comodel_name='hr.form.response.line',
        inverse_name='response_id',
        string='Answers',
    )
    response_count = fields.Integer(
        string='Answer Count',
        compute='_compute_response_count',
    )
    completion_percentage = fields.Float(
        string='Completion %',
        compute='_compute_completion_percentage',
    )
    create_date = fields.Datetime(
        string='Submitted On',
        readonly=True,
    )

    @api.depends('response_line_ids')
    def _compute_response_count(self):
        for response in self:
            response.response_count = len(response.response_line_ids)

    @api.depends('response_line_ids', 'response_line_ids.is_empty')
    def _compute_completion_percentage(self):
        for response in self:
            required_lines = response.response_line_ids.filtered(
                lambda l: l.question_id.is_required
            )
            if required_lines:
                answered = len(required_lines.filtered(lambda l: not l.is_empty))
                response.completion_percentage = (answered / len(required_lines)) * 100
            else:
                # If no required questions, check all questions
                if response.response_line_ids:
                    answered = len(response.response_line_ids.filtered(
                        lambda l: not l.is_empty
                    ))
                    response.completion_percentage = (
                        answered / len(response.response_line_ids)
                    ) * 100
                else:
                    response.completion_percentage = 0

    def name_get(self):
        """Display applicant name and date as name."""
        result = []
        for response in self:
            name = f"{response.applicant_id.partner_name or 'Unknown'} - {response.create_date}"
            result.append((response.id, name))
        return result

    def action_view_applicant(self):
        """Open the related applicant form."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Applicant',
            'res_model': 'hr.applicant',
            'res_id': self.applicant_id.id,
            'view_mode': 'form',
        }

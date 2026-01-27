# -*- coding: utf-8 -*-

from odoo import api, fields, models


class HrFormTemplate(models.Model):
    _name = 'hr.form.template'
    _description = 'HR Form Template'
    _order = 'name'

    name = fields.Char(
        string='Template Name',
        required=True,
        translate=True,
    )
    description = fields.Text(
        string='Description',
        help='Internal description for this template',
    )
    active = fields.Boolean(
        string='Active',
        default=True,
    )
    question_ids = fields.One2many(
        comodel_name='hr.form.question',
        inverse_name='template_id',
        string='Questions',
        copy=True,
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Company',
        default=lambda self: self.env.company,
    )
    question_count = fields.Integer(
        string='Question Count',
        compute='_compute_question_count',
    )
    job_count = fields.Integer(
        string='Jobs Using Template',
        compute='_compute_job_count',
    )

    @api.depends('question_ids', 'question_ids.is_section')
    def _compute_question_count(self):
        for template in self:
            template.question_count = len(
                template.question_ids.filtered(lambda q: not q.is_section)
            )

    @api.depends('question_ids')
    def _compute_job_count(self):
        for template in self:
            template.job_count = self.env['hr.job'].search_count([
                ('form_template_id', '=', template.id)
            ])

    def action_view_jobs(self):
        """Open the list of jobs using this template."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Jobs',
            'res_model': 'hr.job',
            'view_mode': 'tree,form',
            'domain': [('form_template_id', '=', self.id)],
            'context': {'default_form_template_id': self.id},
        }

    def copy(self, default=None):
        """Copy template with all questions."""
        default = dict(default or {})
        default['name'] = f"{self.name} (Copy)"
        return super().copy(default)

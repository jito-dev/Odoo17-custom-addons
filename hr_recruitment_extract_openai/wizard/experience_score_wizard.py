# -*- coding: utf-8 -*-
from odoo import api, fields, models

class ExperienceScoreWizard(models.TransientModel):
    _name = 'hr.recruitment.experience.score.wizard'
    _description = 'Update Experience Score Wizard'

    experience_id = fields.Many2one('hr.applicant.experience', required=True)
    field_to_edit = fields.Char(required=True)
    explanation_field = fields.Char()
    
    score = fields.Float(string="New Score (%)", required=True)
    explanation = fields.Text(string="Explanation")

    def action_apply(self):
        self.ensure_one()
        vals = {self.field_to_edit: self.score}
        if self.explanation_field:
            vals[self.explanation_field] = self.explanation
        self.experience_id.write(vals)
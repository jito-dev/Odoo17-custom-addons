# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class HrApplicant(models.Model):
    _inherit = 'hr.applicant'

    interview_ids = fields.One2many(
        'hr.applicant.interview',
        'applicant_id',
        string="Interviews",
    )
    interview_count = fields.Integer(
        string="Interview Count",
        compute='_compute_interview_count',
    )
    interview_analyzed_count = fields.Integer(
        compute='_compute_interview_count',
    )

    @api.depends('interview_ids.state')
    def _compute_interview_count(self):
        for applicant in self:
            interviews = applicant.interview_ids
            applicant.interview_count = len(interviews)
            applicant.interview_analyzed_count = len(
                interviews.filtered(lambda i: i.state == 'done')
            )

    def action_open_interviews(self):
        """Smart-button action: open this candidate's Fireflies interviews."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Interviews'),
            'res_model': 'hr.applicant.interview',
            'view_mode': 'tree,form',
            'domain': [('applicant_id', '=', self.id)],
            'context': {'default_applicant_id': self.id},
        }

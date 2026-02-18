# -*- coding: utf-8 -*-
from odoo import models, fields, api

class Job(models.Model):
    _inherit = 'hr.job'

    tracker_ids = fields.One2many('hr.recruitment.tracker', 'job_id', string='Link Trackers')
    tracker_count = fields.Integer(compute='_compute_tracker_count', string='Tracker Count')

    @api.depends('tracker_ids')
    def _compute_tracker_count(self):
        for job in self:
            job.tracker_count = len(job.tracker_ids)

    def action_open_trackers(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('hr_recruitment_trackers.action_hr_recruitment_tracker')
        action['domain'] = [('job_id', '=', self.id)]
        action['context'] = {'default_job_id': self.id}
        return action
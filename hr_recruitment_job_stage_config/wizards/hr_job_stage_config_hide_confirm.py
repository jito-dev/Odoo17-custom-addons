# -*- coding: utf-8 -*-
"""Wizard: confirm hiding a stage that still holds applicants.

Stock kanban hide would silently drop the column; we instead prompt
so the recruiter understands the candidates are not deleted but only
hidden behind the 'show hidden' kanban filter and the Stages tab.
"""
from odoo import fields, models


class HrJobStageConfigHideConfirm(models.TransientModel):
    _name = 'hr.job.stage.config.hide.confirm'
    _description = 'Confirm hiding a stage that still holds applicants'

    config_id = fields.Many2one(
        'hr.job.stage.config', required=True, readonly=True)
    applicant_count = fields.Integer(readonly=True)

    job_name = fields.Char(related='config_id.job_id.name', readonly=True)
    stage_name = fields.Char(related='config_id.stage_id.name', readonly=True)

    def action_confirm_hide(self):
        self.ensure_one()
        # Applicants are NEVER touched. Only the visibility flag flips.
        self.config_id.visible = False
        return {'type': 'ir.actions.act_window_close'}

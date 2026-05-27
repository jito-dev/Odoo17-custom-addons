# -*- coding: utf-8 -*-
"""v17.0.4.2.0 — Etap 5: expose per-(job, stage) call-stage configs on
the native `hr.recruitment.stage` form so the kanban gear icon route
into call-stage settings.

The o2m below is the only addition; all editing happens through inline
tree fields on the existing `hr.job.stage.config` model.
"""
from odoo import fields, models


class HrRecruitmentStage(models.Model):
    _inherit = 'hr.recruitment.stage'

    call_stage_config_ids = fields.One2many(
        'hr.job.stage.config', 'stage_id',
        string='Per-job Call Stage configs',
        help='All hr.job.stage.config rows that reference this stage. '
             'Surfaced on the stage form (kanban gear → Edit Stage) so '
             'recruiters can tick `is_call_stage`, pick an Appointment '
             'Type or paste a fixed meeting URL, and assign an email '
             'template without leaving the popup. The o2m is for UI '
             'aggregation only — config rows are still owned by the '
             'foundation, created via its standard lifecycle.')

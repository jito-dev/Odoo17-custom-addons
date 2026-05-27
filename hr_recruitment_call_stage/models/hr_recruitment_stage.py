# -*- coding: utf-8 -*-
"""v17.0.4.2.0 — Etap 5: expose per-(job, stage) call-stage configs on
the native `hr.recruitment.stage` form so the kanban gear icon route
into call-stage settings.

The o2m below is the only addition; all editing happens through inline
tree fields on the existing `hr.job.stage.config` model.
"""
from odoo import api, fields, models


class HrRecruitmentStage(models.Model):
    _inherit = 'hr.recruitment.stage'

    @api.ondelete(at_uninstall=False)
    def _archive_paired_call_booked_on_call_stage_unlink(self):
        """v17.0.7.0.0 — Etap 8: when a Call Stage is deleted (kanban
        gear → Delete Stage), proactively archive every paired Call
        Booked stage attached to its config rows BEFORE the FK CASCADE
        wipes the config rows themselves (which would skip the
        Python-side ondelete on hr.job.stage.config).
        """
        Config = self.env['hr.job.stage.config'].sudo()
        configs = Config.search([
            ('stage_id', 'in', self.ids),
            ('is_call_stage', '=', True),
        ])
        if configs:
            configs._archive_paired_call_booked(
                exclude_config_ids=configs.ids)

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

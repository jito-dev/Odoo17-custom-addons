# -*- coding: utf-8 -*-
from odoo import api, models


class RecruitmentStage(models.Model):
    _inherit = 'hr.recruitment.stage'

    @api.model
    def default_get(self, fields):
        # Stock hr_recruitment.default_get pops `default_job_id` from the
        # context before delegating, which leaves new stages with empty
        # job_ids → they become global, visible in every vacancy. We invert
        # that: when a stage is being created in the context of a specific
        # job, pre-fill job_ids with that job. Respects the `mono` escape
        # hatch and any explicit `default_job_ids` from the caller.
        res = super().default_get(fields)
        job_id = self._context.get('default_job_id')
        if (
            job_id
            and not self._context.get('hr_recruitment_stage_mono', False)
            and 'job_ids' in fields
            and not self._context.get('default_job_ids')
            and not res.get('job_ids')
        ):
            res['job_ids'] = [(6, 0, [job_id])]
        return res

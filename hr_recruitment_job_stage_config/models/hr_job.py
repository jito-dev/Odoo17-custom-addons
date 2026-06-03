# -*- coding: utf-8 -*-
from odoo import api, fields, models


class HrJob(models.Model):
    _inherit = 'hr.job'

    stage_config_ids = fields.One2many(
        'hr.job.stage.config', 'job_id',
        string='Stage configuration',
        copy=True,
        help='Per-stage configuration (sequence, visibility, email template, '
             'reserved fields). Copied when the job is duplicated.')

    hidden_stage_count = fields.Integer(
        compute='_compute_hidden_stage_count',
        string='Hidden stages',
        help='Number of stages explicitly hidden for this job; used by the '
             "kanban banner in PR 3 (zero-noise when 0).")

    use_per_job_test_task_links = fields.Boolean(
        string='Use per-job test-task resource links',
        default=False,
        help='Reserved for PR 4. When enabled, the test-task email and the '
             "applicant form render this job's link_ids on the active stage. "
             'Hidden when off — does not mutate stored link_ids.')

    @api.model_create_multi
    def create(self, vals_list):
        jobs = super().create(vals_list)
        # Auto-populate the Stages tab with all global stages so the user
        # starts with the complete catalogue and only toggles visibility.
        # Skip jobs that already came with explicit stage_config_ids from
        # context/wizard, so we don't create duplicate rows.
        Config = self.env['hr.job.stage.config'].sudo()
        Stage = self.env['hr.recruitment.stage'].sudo()
        global_stages = Stage.search([('job_ids', '=', False)])
        for job in jobs:
            existing_stage_ids = set(job.stage_config_ids.stage_id.ids)
            for stage in global_stages:
                if stage.id in existing_stage_ids:
                    continue
                Config.create({
                    'job_id': job.id,
                    'stage_id': stage.id,
                    'sequence': stage.sequence,
                    'visible': stage.default_visible_in_new_jobs,
                })
        return jobs

    def _sync_stage_configs(self):
        """Ensure every applicable stage has a config row on each job.
        Called from the Stages tab 'Sync' button. Never deletes rows."""
        Config = self.env['hr.job.stage.config'].sudo()
        Stage = self.env['hr.recruitment.stage'].sudo()
        for job in self:
            existing_stage_ids = set(job.stage_config_ids.stage_id.ids)
            applicable = Stage.search([
                '|', ('job_ids', '=', False), ('job_ids', 'in', job.id),
            ])
            for stage in applicable:
                if stage.id in existing_stage_ids:
                    continue
                Config.create({
                    'job_id': job.id,
                    'stage_id': stage.id,
                    'sequence': stage.sequence,
                    'visible': stage.default_visible_in_new_jobs,
                })
        return True

    def action_sync_stage_configs(self):
        self._sync_stage_configs()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'message': 'Stage configuration synchronised.',
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    def action_add_specific_stage(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Add unique stage for this job',
            'res_model': 'hr.job.stage.create.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_job_id': self.id},
        }

    @api.depends('stage_config_ids.visible')
    def _compute_hidden_stage_count(self):
        groups = self.env['hr.job.stage.config']._read_group(
            domain=[
                ('job_id', 'in', self.ids),
                ('visible', '=', False),
            ],
            groupby=['job_id'],
            aggregates=['__count'],
        )
        counts = {job.id: count for job, count in groups}
        for job in self:
            job.hidden_stage_count = counts.get(job.id, 0)

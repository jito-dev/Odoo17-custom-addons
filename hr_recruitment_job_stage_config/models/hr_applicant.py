# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, api, fields, models


class HrApplicant(models.Model):
    _inherit = 'hr.applicant'

    @api.model
    def _read_group_stage_ids(self, stages, domain, order):
        # Replaces stock filtering (job_ids M2M) with config-driven filtering.
        # Goals:
        #   1. In a job-scoped kanban (default_job_id in context), hide stages
        #      explicitly marked visible=False for this job, but ALWAYS show
        #      stages currently hosting applicants (R10 safety: never let an
        #      applicant disappear).
        #   2. Single SQL via stages._search() — no N+1.
        #   3. access_rights_uid=SUPERUSER_ID so the interviewer role keeps
        #      seeing all relevant columns even without write access to stages.
        #   4. order argument preserved.
        job_id = self._context.get('default_job_id')
        if not job_id:
            # General kanban (no job context) — stock behaviour: only globals.
            search_domain = [('scope', '=', 'global')]
            if stages:
                search_domain = ['|', ('id', 'in', stages.ids)] + search_domain
            stage_ids = stages._search(
                search_domain, order=order, access_rights_uid=SUPERUSER_ID)
            return stages.browse(stage_ids)

        Config = self.env['hr.job.stage.config'].sudo()
        configs = Config.search([('job_id', '=', job_id)])
        hidden_stage_ids = configs.filtered(lambda c: not c.visible).stage_id.ids
        visible_specific_stage_ids = (
            configs.filtered(lambda c: c.visible).stage_id.ids
        )

        # Stage S is visible to this job iff:
        #   (scope='global' AND S not in hidden_stage_ids)
        #   OR (scope='specific' AND S in visible_specific_stage_ids)
        #   OR S currently hosts an applicant (always-on safety)
        global_clause = [
            '&',
            ('scope', '=', 'global'),
            ('id', 'not in', hidden_stage_ids or [0]),
        ]
        specific_clause = [
            '&',
            ('scope', '=', 'specific'),
            ('id', 'in', visible_specific_stage_ids or [0]),
        ]
        search_domain = ['|'] + global_clause + specific_clause
        if stages:
            # Currently grouped stages always remain visible — even if their
            # config flipped to invisible after the applicant landed there.
            search_domain = ['|', ('id', 'in', stages.ids)] + search_domain

        stage_ids = stages._search(
            search_domain, order=order, access_rights_uid=SUPERUSER_ID)
        return stages.browse(stage_ids)

    @api.depends('job_id')
    def _compute_stage(self):
        # Overrides stock to skip stages hidden for this job via config rows.
        # Without this override, a new applicant could land on a hidden stage
        # and vanish from the kanban (R10).
        Config = self.env['hr.job.stage.config'].sudo()
        Stage = self.env['hr.recruitment.stage'].sudo()
        for applicant in self:
            if not applicant.job_id:
                applicant.stage_id = False
                continue
            if applicant.stage_id:
                continue

            configs_for_job = Config.search([('job_id', '=', applicant.job_id.id)])
            hidden_stage_ids = set(
                configs_for_job.filtered(lambda c: not c.visible).stage_id.ids
            )
            visible_specific_stage_ids = set(
                configs_for_job.filtered(lambda c: c.visible).stage_id.ids
            )
            sequence_override = {
                c.stage_id.id: c.sequence for c in configs_for_job
            }

            # Candidate stages: globals (not hidden) + visible specifics
            stages = Stage.search([
                '|',
                '&', ('scope', '=', 'global'),
                     ('id', 'not in', list(hidden_stage_ids) or [0]),
                '&', ('scope', '=', 'specific'),
                     ('id', 'in', list(visible_specific_stage_ids) or [0]),
            ])
            non_folded = stages.filtered(lambda s: not s.fold)
            if not non_folded:
                applicant.stage_id = False
                continue

            ordered = sorted(
                non_folded,
                key=lambda s: (
                    sequence_override.get(s.id, s.sequence),
                    s.id,
                ),
            )
            applicant.stage_id = ordered[0].id

    def _track_template(self, changes):
        # Replace the stock stage_id template entry (stage.template_id) with
        # the per-job override resolved via hr.job.stage.config. Source of
        # truth: config.mail_template_id; fallback: stage.template_id.
        # Eager resolution returns a real recordset — Odoo 17 _track_template
        # does NOT accept callables.
        res = super()._track_template(changes)
        if 'stage_id' not in changes:
            return res
        applicant = self[0]
        if not applicant.exists() or applicant._context.get('just_unarchived'):
            return res
        Config = self.env['hr.job.stage.config'].sudo()
        config = Config.search([
            ('job_id', '=', applicant.job_id.id),
            ('stage_id', '=', applicant.stage_id.id),
        ], limit=1)
        template = (
            config.mail_template_id
            or applicant.stage_id.template_id
        )
        if template:
            res['stage_id'] = (template, {
                'auto_delete_keep_log': False,
                'subtype_id': self.env['ir.model.data']._xmlid_to_res_id('mail.mt_note'),
                'email_layout_xmlid': 'hr_recruitment.mail_notification_light_without_background',
            })
        else:
            res.pop('stage_id', None)
        return res

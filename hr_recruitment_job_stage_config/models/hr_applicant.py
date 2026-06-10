# -*- coding: utf-8 -*-
import logging

from odoo import SUPERUSER_ID, _, api, fields, models

_logger = logging.getLogger(__name__)


class HrApplicant(models.Model):
    _inherit = 'hr.applicant'

    # v17.0.1.0.11 — replaces stock stage_id domain
    # ['|', ('job_ids', '=', False), ('job_ids', '=', job_id)] which is unaware
    # of hr.job.stage.config.visible. The new domain references allowed_stage_ids,
    # a non-stored computed M2M built via the shared _visible_stages_domain
    # helper. This makes every Many2one widget (form dropdown, statusbar, tree
    # inline-edit, kanban quick-create, search autocomplete) honour the same
    # visibility rules as the kanban grouping (_read_group_stage_ids).
    # See docs/migration_17_0_1_0_11_instruction.md.
    stage_id = fields.Many2one(
        'hr.recruitment.stage', 'Stage',
        ondelete='restrict', tracking=True,
        compute='_compute_stage', store=True, readonly=False,
        domain="[('id', 'in', allowed_stage_ids)]",
        copy=False, index=True,
        group_expand='_read_group_stage_ids',
    )

    allowed_stage_ids = fields.Many2many(
        'hr.recruitment.stage',
        compute='_compute_allowed_stage_ids',
        string='Allowed stages',
        help='Computed set of stages selectable for this applicant. Mirrors '
             'the kanban visibility logic via the shared _visible_stages_domain '
             "helper. Always includes the applicant's current stage_id (R10 "
             'safety: a stage hosting this applicant remains selectable even '
             'if config flipped it to hidden afterwards).')

    @api.model
    def _visible_stages_domain(self, job_id, current_stage_ids=()):
        """Single source of truth: search domain on hr.recruitment.stage
        selecting stages visible for ``job_id``, plus any id in
        ``current_stage_ids`` (R10 safety).

        Shared by:
          * ``_read_group_stage_ids`` — kanban grouping;
          * ``_compute_allowed_stage_ids`` — form/statusbar/tree dropdown
            domain via the ``allowed_stage_ids`` non-stored M2M.

        Rule:
          (scope='global'   AND id NOT IN hidden_for_job)
          OR (scope='specific' AND id IN visible_specific_for_job)
          OR (id IN current_stage_ids)   -- R10

        When ``job_id`` is falsy (general kanban / applicant without a job),
        falls back to ``scope='global'`` plus the R10 OR-branch.
        """
        if not job_id:
            domain = [('scope', '=', 'global')]
            if current_stage_ids:
                domain = ['|', ('id', 'in', list(current_stage_ids))] + domain
            return domain

        Config = self.env['hr.job.stage.config'].sudo()
        configs = Config.search([('job_id', '=', job_id)])
        hidden_stage_ids = configs.filtered(lambda c: not c.visible).stage_id.ids
        visible_specific_stage_ids = (
            configs.filtered(lambda c: c.visible).stage_id.ids
        )

        domain = [
            '|',
            '&', ('scope', '=', 'global'),
                 ('id', 'not in', hidden_stage_ids or [0]),
            '&', ('scope', '=', 'specific'),
                 ('id', 'in', visible_specific_stage_ids or [0]),
        ]
        if current_stage_ids:
            domain = ['|', ('id', 'in', list(current_stage_ids))] + domain
        return domain

    @api.depends('job_id', 'stage_id')
    def _compute_allowed_stage_ids(self):
        Stage = self.env['hr.recruitment.stage'].sudo()
        for applicant in self:
            current_ids = applicant.stage_id.ids if applicant.stage_id else ()
            domain = self._visible_stages_domain(
                applicant.job_id.id if applicant.job_id else False,
                current_ids,
            )
            applicant.allowed_stage_ids = Stage.search(domain)

    @api.model
    def _read_group_stage_ids(self, stages, domain, order):
        # Delegates to _visible_stages_domain so kanban grouping and field
        # dropdown share one rule. access_rights_uid=SUPERUSER_ID kept so the
        # interviewer role still sees all columns without stage write access.
        job_id = self._context.get('default_job_id')
        current_ids = stages.ids if stages else ()
        search_domain = self._visible_stages_domain(job_id, current_ids)
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
        # Guard before super(): stock hr_recruitment._track_template does
        # self[0] unconditionally and crashes on an empty recordset.
        if not self:
            return {}
        res = super()._track_template(changes)
        if 'stage_id' not in changes:
            return res
        applicant = self[:1]
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
        if template and (not template.model_id or template.model != 'hr.applicant'):
            # PR 2.5 runtime guard: a leftover broken template (model_id
            # NULL or non-applicant model) reaches us in production via
            # legacy data or out-of-band writes. Skip the email rather
            # than crash at self.env[self.model] in mail_template, and
            # surface the misconfiguration to the recruiter via chatter
            # so it does not silently swallow notifications.
            _logger.error(
                "hr_recruitment_job_stage_config: skipped stage email for "
                "applicant id=%s (job=%s, stage=%s) — template id=%s has "
                "model=%r (expected hr.applicant). Re-pick a valid "
                "template in the stage config popup.",
                applicant.id, applicant.job_id.id, applicant.stage_id.id,
                template.id, template.model,
            )
            applicant.message_post(body=_(
                "Stage email skipped: the template assigned to stage "
                "'%(stage)s' is misconfigured (model = %(model)s). "
                "Ask an administrator to re-pick a valid Applicant "
                "template in the job's Stages configuration.",
                stage=applicant.stage_id.display_name,
                model=template.model or _('(not set)'),
            ))
            res.pop('stage_id', None)
            return res
        if template:
            res['stage_id'] = (template, {
                'auto_delete_keep_log': False,
                'subtype_id': self.env['ir.model.data']._xmlid_to_res_id('mail.mt_note'),
                'email_layout_xmlid': 'hr_recruitment.mail_notification_light_without_background',
            })
        else:
            res.pop('stage_id', None)
        return res

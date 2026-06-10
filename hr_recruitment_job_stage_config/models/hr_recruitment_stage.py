# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.tools import SQL


# Stages that ship visible-by-default on a freshly created job.
# Matched by exact name; any other stage defaults to hidden so the job's
# Stages tab is a clean, opinionated workflow rather than the full pile.
DEFAULT_VISIBLE_STAGE_NAMES = (
    'New',
    'Initial Qualification',
    'First Interview',
    'Second Interview',
    'Contract Proposal',
)


class HrRecruitmentStage(models.Model):
    _inherit = 'hr.recruitment.stage'

    default_visible_in_new_jobs = fields.Boolean(
        string='Visible by default in new jobs',
        default=False,
        help='When a new job is created, the auto-generated config row for '
             'this stage starts with visible=True only if this flag is set. '
             'Defaults to True only for the canonical workflow stages '
             '(New, Initial Qualification, First Interview, Second Interview, '
             'Contract Proposal); everything else opt-in per job.')

    stage_config_ids = fields.One2many(
        'hr.job.stage.config', 'stage_id',
        string='Per-job configurations',
        help='Inverse relation to hr.job.stage.config. Exposes the per-job '
             'payload (visibility, sequence, mail template override, ...) '
             'attached to this stage. Used by the allowed_stage_ids '
             'computation on hr.applicant (v17.0.1.0.11) — single source of '
             'truth for which stages are visible per job.')

    display_fold = fields.Boolean(
        compute='_compute_display_fold',
        help='Per-job fold override when the read context carries '
             "``applicant_stage_job_id``; otherwise mirrors ``stage.fold``. "
             "Consumed by the statusbar widget on the applicant form so the "
             "kanban-like fold can differ per vacancy without mutating the "
             'global stage flag.')

    scope = fields.Selection(
        selection=[
            ('global', 'Global (visible in every job)'),
            ('specific', 'Specific to selected jobs'),
        ],
        string='Scope',
        compute='_compute_scope', inverse='_inverse_scope',
        store=True, precompute=True,
        help='Switcher mirroring the job_ids state. '
             "'Global' = job_ids empty; 'Specific' = job_ids contains jobs. "
             "Editable via the form switcher; the inverse keeps job_ids in sync. "
             "NO `default=` — see v17.0.1.0.6: a static default fills vals "
             "before precompute, which makes precompute skip the field AND "
             "causes _inverse_scope to fire after INSERT (clearing the M2M "
             "job_ids that the kanban '+ Stage' path just set). Letting the "
             "precompute path own the initial value is the only correct flow.")

    @api.depends('job_ids')
    def _compute_scope(self):
        for stage in self:
            stage.scope = 'specific' if stage.job_ids else 'global'

    def _inverse_scope(self):
        # Guard against post-INSERT wipes: when a stage is being created from a
        # job kanban "+ Stage" path, precompute may evaluate scope='global'
        # before job_ids defaults are applied. The post-INSERT inverse would
        # then clear the M2M that default_get/create just injected. The
        # `default_job_id` context (kanban path) and the explicit
        # `skip_inverse_scope` flag (programmatic callers) both opt out.
        if self.env.context.get('default_job_id') \
                or self.env.context.get('skip_inverse_scope'):
            return
        Config = self.env['hr.job.stage.config']
        Job = self.env['hr.job']
        for stage in self:
            # New (in-memory) records never need the wipe: the compute will
            # resync `scope` from `job_ids` on first read.
            if not stage.id:
                continue
            if stage.scope == 'global':
                # v17.0.1.0.14: preserve all existing config rows AND create
                # rows for every other job so the invariant "every applicable
                # stage has a config row on every job" holds. Previously,
                # auto-rows (no payload) were deleted on flip — that left
                # the stage visible in kanban (no row = not hidden) but
                # absent from the Stages tab (which lists config rows). The
                # Stages tab and the kanban are now consistent.
                existing_job_ids = set(
                    Config.sudo().search([('stage_id', '=', stage.id)])
                    .mapped('job_id').ids
                )
                all_jobs = Job.sudo().search([])
                for job in all_jobs:
                    if job.id in existing_job_ids:
                        continue
                    Config.sudo().create({
                        'job_id': job.id,
                        'stage_id': stage.id,
                        'sequence': stage.sequence,
                        'visible': stage.default_visible_in_new_jobs,
                    })
                stage.job_ids = [(5, 0, 0)]
            else:
                # 'specific' requires at least one job. If user toggles scope
                # without picking a job yet, we leave job_ids untouched and
                # rely on view validation.
                for job in stage.job_ids:
                    Config.search([
                        ('job_id', '=', job.id),
                        ('stage_id', '=', stage.id),
                    ]) or Config.create({
                        'job_id': job.id,
                        'stage_id': stage.id,
                        'sequence': stage.sequence,
                    })

    @api.model
    def default_get(self, fields_list):
        # Override stock hr_recruitment behaviour: instead of popping
        # default_job_id from context (which makes the new stage global),
        # carry it through and pre-fill job_ids. Mirrors the standalone
        # hr_recruitment_stage_default_fix module — kept compatible so both
        # can coexist. The mono escape hatch is still honoured.
        res = super().default_get(fields_list)
        job_id = self._context.get('default_job_id')
        if (
            job_id
            and not self._context.get('hr_recruitment_stage_mono', False)
            and 'job_ids' in fields_list
            and not self._context.get('default_job_ids')
            and not res.get('job_ids')
        ):
            res['job_ids'] = [(6, 0, [job_id])]
        return res

    def write(self, vals):
        # _inverse_scope only fires when `scope` is written explicitly. If a
        # caller writes job_ids directly (the path downstream modules like
        # hr_recruitment_test_task and iq_tests_survey use), the inverse is
        # never called and config rows are never created — leaving the stage
        # invisible in the kanban. Capture job_ids before super, then sync
        # configs for any newly-added jobs.
        before_jobs = (
            {stage.id: set(stage.job_ids.ids) for stage in self}
            if 'job_ids' in vals else {}
        )
        res = super().write(vals)
        if 'job_ids' in vals:
            for stage in self:
                added = set(stage.job_ids.ids) - before_jobs.get(stage.id, set())
                if added:
                    stage._ensure_config_rows_for_jobs(added)
        return res

    @api.model_create_multi
    def create(self, vals_list):
        # Belt-and-suspenders for the kanban "+ Stage" path: some entry
        # points (column quick-create, name_create, wizards) bypass the
        # default_get override above by passing explicit vals. If the
        # context still carries default_job_id and vals does not pin
        # job_ids, inject the current job here so the stage is born
        # specific-to-this-job (not global). mono escape still honoured.
        ctx_job_id = self._context.get('default_job_id')
        if (
            ctx_job_id
            and not self._context.get('hr_recruitment_stage_mono', False)
        ):
            for vals in vals_list:
                if not vals.get('job_ids'):
                    vals['job_ids'] = [(6, 0, [ctx_job_id])]
        stages = super().create(vals_list)
        # Belt-and-suspenders against the post-INSERT inverse wipe: if any
        # other code path (precompute race, downstream write) cleared job_ids
        # after super().create, re-pin them here while we still know the
        # source job. Write only `job_ids` (not `scope`) so the inverse is not
        # invoked again; the compute will sync `scope='specific'` on next read.
        if ctx_job_id and not self._context.get('hr_recruitment_stage_mono', False):
            for stage in stages:
                if ctx_job_id not in stage.job_ids.ids:
                    stage.with_context(skip_inverse_scope=True).write({
                        'job_ids': [(4, ctx_job_id)],
                    })
        # For every newly created global stage, materialise a config row on
        # every existing job so the Stages tab shows the complete catalogue.
        # For job-specific stages (created with job_ids set), create config
        # rows for the listed jobs — _inverse_scope only fires when `scope`
        # is written explicitly, not when job_ids alone is written.
        Config = self.env['hr.job.stage.config'].sudo()
        Job = self.env['hr.job'].sudo()
        all_jobs = Job.search([])
        for stage in stages:
            if stage.job_ids:
                stage._ensure_config_rows_for_jobs(stage.job_ids.ids)
                continue
            for job in all_jobs:
                exists = Config.search_count([
                    ('job_id', '=', job.id),
                    ('stage_id', '=', stage.id),
                ])
                if exists:
                    continue
                Config.create({
                    'job_id': job.id,
                    'stage_id': stage.id,
                    'sequence': stage.sequence,
                    'visible': stage.default_visible_in_new_jobs,
                })
        return stages

    def _ensure_config_rows_for_jobs(self, job_ids):
        """Idempotently create hr.job.stage.config rows for (self, job) pairs.

        Visible defaults to True so that downstream toggles (add_test_task,
        add_iq_test, etc.) make the stage immediately visible in the job
        kanban — without each downstream module needing to know about
        hr.job.stage.config. A pre-existing row is never modified, so a
        recruiter's manual `visible=False` is preserved across re-toggles.
        """
        self.ensure_one()
        if not job_ids:
            return
        Config = self.env['hr.job.stage.config'].sudo()
        for job_id in job_ids:
            exists = Config.search_count([
                ('job_id', '=', job_id),
                ('stage_id', '=', self.id),
            ])
            if exists:
                continue
            Config.create({
                'job_id': job_id,
                'stage_id': self.id,
                'sequence': self.sequence,
                'visible': True,
            })

    @api.depends('fold')
    @api.depends_context('applicant_stage_job_id')
    def _compute_display_fold(self):
        job_id = self._context.get('applicant_stage_job_id')
        try:
            job_id = int(job_id) if job_id else 0
        except (TypeError, ValueError):
            job_id = 0
        if not job_id:
            for stage in self:
                stage.display_fold = stage.fold
            return
        Config = self.env['hr.job.stage.config'].sudo()
        configs = Config.search([
            ('job_id', '=', job_id),
            ('stage_id', 'in', self.ids),
        ])
        per_stage = {c.stage_id.id: c.fold for c in configs}
        for stage in self:
            # No config row → no per-job override → fall back to the global
            # stage flag. Matches the runtime fallback used elsewhere when a
            # legacy global stage has not yet been backfilled for this job.
            stage.display_fold = per_stage.get(stage.id, stage.fold)

    def _order_to_sql(self, order, query, alias=None, reverse=False):
        # Inject per-job ORDER BY when the caller has identified the applicant's
        # job via context. Statusbar / dropdown / search_read all hit `_search`
        # without an explicit `order`, falling back to `self._order`; that is the
        # ONLY case we touch. Custom `order=...` callers stay unaffected.
        sql_order = super()._order_to_sql(order, query, alias, reverse)
        job_id = self._context.get('applicant_stage_job_id')
        try:
            job_id = int(job_id) if job_id else 0
        except (TypeError, ValueError):
            job_id = 0
        if not job_id or (order and order != self._order):
            return sql_order
        # _flush_search only flushes fields of models referenced in the domain
        # / order string. Our JOIN reaches into hr.job.stage.config, which the
        # ORM cannot see — force a flush of the columns the JOIN touches so
        # pending in-memory writes (e.g. a recruiter reordering stages in the
        # Stages tab) are visible to the SELECT.
        self.env['hr.job.stage.config'].flush_model(['sequence', 'job_id', 'stage_id'])
        table_alias = alias or self._table
        config_alias = query.make_alias(table_alias, 'job_stage_config')
        query.add_join(
            'LEFT JOIN', config_alias, 'hr_job_stage_config',
            SQL(
                '%s = %s AND %s = %s',
                SQL.identifier(table_alias, 'id'),
                SQL.identifier(config_alias, 'stage_id'),
                SQL.identifier(config_alias, 'job_id'),
                job_id,
            ),
        )
        direction = SQL('DESC') if reverse else SQL('ASC')
        nulls = SQL('NULLS FIRST') if reverse else SQL('NULLS LAST')
        return SQL(
            '%s %s %s, %s',
            SQL.identifier(config_alias, 'sequence'),
            direction,
            nulls,
            sql_order,
        )

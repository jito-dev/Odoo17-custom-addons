# -*- coding: utf-8 -*-
from .common import StageConfigTestCommon


class TestStageScope(StageConfigTestCommon):
    def test_default_get_with_job_context_makes_stage_specific(self):
        """Creating a stage with default_job_id context pre-fills job_ids and
        therefore yields scope='specific'."""
        ctx = {'default_job_id': self.job_a.id}
        stage = self.Stage.with_context(**ctx).create({
            'name': 'JSC scoped via context',
        })
        self.assertIn(self.job_a, stage.job_ids,
            "Stage created with default_job_id must include that job")
        self.assertEqual(stage.scope, 'specific')

    def test_default_get_without_job_context_makes_stage_global(self):
        stage = self.Stage.create({'name': 'JSC global stage'})
        self.assertFalse(stage.job_ids)
        self.assertEqual(stage.scope, 'global')

    def test_default_get_respects_mono_escape_hatch(self):
        """The legacy hr_recruitment_stage_mono flag opts back into stock
        behaviour for any caller that needs it."""
        ctx = {
            'default_job_id': self.job_a.id,
            'hr_recruitment_stage_mono': True,
        }
        stage = self.Stage.with_context(**ctx).create({
            'name': 'JSC mono escape',
        })
        self.assertFalse(stage.job_ids,
            "mono context must restore stock 'global' default")

    def test_inverse_scope_global_clears_job_ids_and_deletes_auto_rows(self):
        stage = self._create_stage(
            'JSC scope flip stage', job_ids=[self.job_a, self.job_b])
        # _inverse_scope on 'specific' creates the auto-rows; they may or
        # may not exist depending on view path. Force-create them.
        for job in (self.job_a, self.job_b):
            self.Config.search([
                ('job_id', '=', job.id),
                ('stage_id', '=', stage.id),
            ]) or self.Config.create({
                'job_id': job.id,
                'stage_id': stage.id,
                'sequence': stage.sequence,
            })

        stage.scope = 'global'
        self.assertFalse(stage.job_ids,
            "scope='global' must clear job_ids")
        self.assertFalse(
            self.Config.search([('stage_id', '=', stage.id)]),
            "auto-rows (no payload) must be deleted when flipping to global")

    def test_inverse_scope_global_preserves_override_rows(self):
        """Config rows that carry payload (e.g. mail_template_id) survive
        a scope flip so the user can decide what to do."""
        template = self.MailTemplate.create({
            'name': 'JSC payload template',
            'model_id': self.env.ref('hr_recruitment.model_hr_applicant').id,
            'subject': 'Hello {{ object.partner_name }}',
            'body_html': 'Greetings',
        })
        stage = self._create_stage(
            'JSC override flip stage', job_ids=[self.job_a])
        cfg = self.Config.search([
            ('job_id', '=', self.job_a.id),
            ('stage_id', '=', stage.id),
        ]) or self.Config.create({
            'job_id': self.job_a.id,
            'stage_id': stage.id,
            'mail_template_id': template.id,
            'sequence': stage.sequence,
        })
        cfg.mail_template_id = template

        stage.scope = 'global'
        self.assertTrue(
            self.Config.browse(cfg.id).exists(),
            "rows with payload must survive global flip")

    def test_scope_compute_follows_job_ids(self):
        stage = self._create_stage('JSC compute stage')
        self.assertEqual(stage.scope, 'global')
        stage.job_ids = [(4, self.job_a.id)]
        # scope is computed+stored — flush to trigger recompute
        stage.flush_recordset(['scope'])
        self.assertEqual(stage.scope, 'specific')

    def test_inverse_scope_noop_during_create_with_default_job_id(self):
        """Regression for v17.0.1.0.7.

        Even if `_inverse_scope` fires during the kanban "+ Stage" create
        (precompute race), it must not clear the M2M `job_ids` that the
        create override injected. The guard short-circuits the inverse when
        `default_job_id` is in the context.
        """
        ctx = {'default_job_id': self.job_a.id}
        stage = self.Stage.with_context(**ctx).create({
            'name': 'JSC inverse guard stage',
        })
        self.Stage.invalidate_model(['scope', 'job_ids'])
        self.assertIn(self.job_a, stage.job_ids,
            "_inverse_scope must not wipe job_ids when default_job_id is in "
            "context (kanban create path)")
        self.assertEqual(stage.scope, 'specific')

    def test_inverse_scope_still_wipes_outside_create(self):
        """The form-switcher contract still works post-create: flipping a
        specific stage to scope='global' from a clean context must clear
        job_ids. The guard only protects the kanban create path."""
        stage = self._create_stage(
            'JSC switcher post-create', job_ids=[self.job_a])
        # Plain env context — no default_job_id, no skip_inverse_scope.
        stage.scope = 'global'
        self.assertFalse(stage.job_ids,
            "scope='global' outside create context must still wipe job_ids")

    def test_scope_persisted_as_specific_on_kanban_create(self):
        """Regression for v17.0.1.0.6.

        Clicking '+ Stage' on a vacancy kanban must persist scope='specific'
        in the DB and keep the M2M ``job_ids`` populated. Prior fix attempts
        (v17.0.1.0.5: `precompute=True`) were insufficient: the static
        `default='global'` made it into vals via `_add_missing_default_values`,
        bypassing precompute and triggering `_inverse_scope` after INSERT,
        which then cleared the M2M.

        This test asserts BOTH the stored scope AND the surviving job_ids,
        bypassing any in-memory cache.
        """
        ctx = {'default_job_id': self.job_a.id}
        stage = self.Stage.with_context(**ctx).create({
            'name': 'JSC kanban regression stage',
        })
        # 1. M2M was set by the create override AND survived the post-INSERT
        #    inverse phase. This is the assertion that caught the v17.0.1.0.5
        #    half-fix.
        self.assertIn(self.job_a, stage.job_ids,
            "Kanban '+ Stage' must leave the M2M populated; if it is empty, "
            "_inverse_scope fired after INSERT and cleared it.")
        # 2. Read scope back from the DB, not from cache — this is what the
        #    form view does when the user clicks the gear icon.
        self.Stage.invalidate_model(['scope'])
        self.assertEqual(stage.scope, 'specific',
            "Stage created from a job kanban must be stored as scope='specific' "
            "in the DB.")
        # 3. Exactly one config row exists for (job_a, stage) and it is visible
        #    so the kanban column shows up immediately. Prior bug: the empty
        #    job_ids forced the create-loop into the global branch which made
        #    config rows for every job with visible=False.
        configs = self.Config.search([('stage_id', '=', stage.id)])
        self.assertEqual(len(configs), 1,
            "exactly one (job, stage) config row should be auto-created for "
            "the kanban-source job — not one per job in the database.")
        self.assertEqual(configs.job_id, self.job_a)
        self.assertTrue(configs.visible,
            "auto-created config row must be visible so the kanban column "
            "shows up immediately for the user who just created it.")

# -*- coding: utf-8 -*-
"""Tests for the hide-stage safety popup.

- empty stage  → action_toggle_visible flips visible to False silently
- non-empty    → returns a confirm wizard; applicants never get deleted
"""
from .common import StageConfigTestCommon


class TestHideSafety(StageConfigTestCommon):

    def test_toggle_empty_stage_is_silent(self):
        stage = self._create_stage('Quiet Hide JSC')
        config = self.Config.search([
            ('job_id', '=', self.job_a.id),
            ('stage_id', '=', stage.id),
        ], limit=1)
        config.visible = True
        result = config.action_toggle_visible()
        self.assertTrue(result is True,
                        'Empty toggle returns True, not an action dict.')
        self.assertFalse(config.visible)

    def test_toggle_with_applicants_returns_wizard(self):
        stage = self._create_stage('Crowded Hide JSC')
        config = self.Config.search([
            ('job_id', '=', self.job_a.id),
            ('stage_id', '=', stage.id),
        ], limit=1)
        config.visible = True
        self._create_applicant('Applicant JSC', self.job_a, stage=stage)
        config.invalidate_recordset()

        result = config.action_toggle_visible()
        self.assertIsInstance(result, dict)
        self.assertEqual(result.get('res_model'),
                         'hr.job.stage.config.hide.confirm')
        # And critically: visibility unchanged until user confirms.
        self.assertTrue(config.visible,
                        'Visible must NOT flip until user confirms.')

    def test_hidden_stage_count_reflects_visibility(self):
        """The job.hidden_stage_count badge above the Stages tab must
        match the number of config rows with visible=False."""
        # Baseline: count current hidden rows on job_a so the test is
        # robust to default_visible_in_new_jobs seeding behaviour.
        self.job_a.invalidate_recordset(['hidden_stage_count'])
        baseline = self.job_a.hidden_stage_count

        stage1 = self._create_stage('Hidden count A JSC')
        stage2 = self._create_stage('Hidden count B JSC')
        cfg1 = self.Config.search([
            ('job_id', '=', self.job_a.id), ('stage_id', '=', stage1.id),
        ], limit=1)
        cfg2 = self.Config.search([
            ('job_id', '=', self.job_a.id), ('stage_id', '=', stage2.id),
        ], limit=1)
        # Ensure starting state is visible (auto-create defaults to True for
        # global stages without payload; force-set to remove ambiguity).
        (cfg1 + cfg2).write({'visible': True})
        self.job_a.invalidate_recordset(['hidden_stage_count'])
        self.assertEqual(self.job_a.hidden_stage_count, baseline)

        cfg1.visible = False
        self.job_a.invalidate_recordset(['hidden_stage_count'])
        self.assertEqual(self.job_a.hidden_stage_count, baseline + 1)

        cfg2.visible = False
        self.job_a.invalidate_recordset(['hidden_stage_count'])
        self.assertEqual(self.job_a.hidden_stage_count, baseline + 2)

    def test_stage_scope_related_field_mirrors_stage(self):
        """The view-only related `stage_scope` field on config must reflect
        the underlying stage.scope so the Stages tab can decorate/group by
        scope without coupling to the inverse on hr.recruitment.stage."""
        global_stage = self._create_stage('Scope mirror G JSC')
        specific_stage = self._create_stage(
            'Scope mirror S JSC', job_ids=[self.job_a])

        cfg_global = self.Config.search([
            ('job_id', '=', self.job_a.id), ('stage_id', '=', global_stage.id),
        ], limit=1)
        cfg_specific = self.Config.search([
            ('job_id', '=', self.job_a.id), ('stage_id', '=', specific_stage.id),
        ], limit=1)

        self.assertEqual(cfg_global.stage_scope, 'global')
        self.assertEqual(cfg_specific.stage_scope, 'specific')

    def test_confirm_wizard_hides_and_keeps_applicants(self):
        stage = self._create_stage('Confirm Hide JSC')
        config = self.Config.search([
            ('job_id', '=', self.job_a.id),
            ('stage_id', '=', stage.id),
        ], limit=1)
        config.visible = True
        app = self._create_applicant('Keepme JSC', self.job_a, stage=stage)

        wizard = self.env['hr.job.stage.config.hide.confirm'].create({
            'config_id': config.id,
            'applicant_count': 1,
        })
        wizard.action_confirm_hide()
        self.assertFalse(config.visible)
        self.assertTrue(app.exists(),
                        'Applicant must survive a stage being hidden.')
        self.assertEqual(app.stage_id, stage,
                         'Applicant stage_id must remain unchanged.')

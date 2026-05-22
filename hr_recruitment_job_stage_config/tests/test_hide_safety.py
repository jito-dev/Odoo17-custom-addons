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

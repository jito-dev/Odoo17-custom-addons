# -*- coding: utf-8 -*-
"""v17.0.1.0.11 — allowed_stage_ids reflects per-job config visibility.

Covers the form dropdown / statusbar / tree inline-edit / kanban
quick-create domain (all driven by the same field-level
`domain="[('id', 'in', allowed_stage_ids)]"`). Each scenario asserts
on hr.applicant.allowed_stage_ids — the computed M2M sitting under
the field domain.
"""
from odoo.tests.common import tagged

from .common import StageConfigTestCommon


@tagged('post_install', '-at_install')
class TestStageDropdownDomain(StageConfigTestCommon):

    def test_dropdown_hides_invisible_stage(self):
        # Stage S is specific to job_a. Flip its config to visible=False
        # → S must NOT be in allowed_stage_ids for a NEW applicant of job_a.
        stage_s = self._create_stage('JSC Visibility S', job_ids=[self.job_a])
        config = self.Config.search([
            ('job_id', '=', self.job_a.id),
            ('stage_id', '=', stage_s.id),
        ])
        self.assertTrue(config, 'Backfill must create config row for specific stage')
        config.visible = False

        # A fresh applicant on job_a; _compute_stage already steers stage_id
        # away from hidden stages, so build allowed_stage_ids on a record
        # whose stage_id is NOT stage_s (avoids R10 OR branch).
        applicant = self._create_applicant('JSC Applicant New', self.job_a)
        self.assertNotIn(
            stage_s, applicant.allowed_stage_ids,
            'Hidden specific stage must be excluded from dropdown')

    def test_dropdown_includes_current_stage_even_if_hidden(self):
        # R10 safety. Applicant already sits on stage_s; flip to hidden;
        # stage_s must STILL be selectable on that applicant's form.
        stage_s = self._create_stage('JSC R10 S', job_ids=[self.job_a])
        config = self.Config.search([
            ('job_id', '=', self.job_a.id),
            ('stage_id', '=', stage_s.id),
        ])
        applicant = self._create_applicant('JSC R10 Applicant', self.job_a, stage=stage_s)
        config.visible = False
        applicant.invalidate_recordset(['allowed_stage_ids'])
        self.assertIn(
            stage_s, applicant.allowed_stage_ids,
            'Current stage must remain in allowed set (R10) even after hide')

    def test_dropdown_includes_global_without_config_row(self):
        # Legacy: a global stage with NO config row anywhere must remain
        # allowed (defaults to visible). Domain branch:
        #   scope='global' AND id NOT IN hidden_for_job
        global_stage = self._create_stage('JSC Legacy Global', job_ids=None)
        # Strip the auto-seeded config rows so we test the legacy
        # "no config row anywhere" path (auto-seed in create() is the
        # post-1.0.0 codepath; this test pins the fallback behaviour).
        self.Config.search([('stage_id', '=', global_stage.id)]).unlink()
        self.assertEqual(global_stage.scope, 'global')
        applicant = self._create_applicant('JSC Legacy Applicant', self.job_a)
        self.assertIn(
            global_stage, applicant.allowed_stage_ids,
            'Global stage with no config row must default to allowed')

    def test_dropdown_excludes_specific_stage_of_other_job(self):
        # Stage X is specific to job_a only. Applicant of job_b must NOT
        # see X in their dropdown.
        stage_x = self._create_stage('JSC Specific to A', job_ids=[self.job_a])
        applicant_b = self._create_applicant('JSC B Applicant', self.job_b)
        self.assertNotIn(
            stage_x, applicant_b.allowed_stage_ids,
            "Specific stage of another job must be hidden")

    def test_dropdown_no_job_falls_back_to_globals(self):
        # Applicant with no job_id — only globals visible. Mirrors the
        # general kanban behaviour in _read_group_stage_ids.
        global_stage = self._create_stage('JSC Global Fallback', job_ids=None)
        specific_stage = self._create_stage('JSC Specific Fallback', job_ids=[self.job_a])
        applicant = self.Applicant.create({
            'name': 'JSC No Job',
            'partner_name': 'JSC No Job',
        })
        self.assertFalse(applicant.job_id)
        self.assertIn(global_stage, applicant.allowed_stage_ids)
        self.assertNotIn(specific_stage, allowed_stage_ids := applicant.allowed_stage_ids,
                         "Specific stage must not appear when applicant has no job")
        # Reference the walrus result so linters don't flag it
        self.assertTrue(allowed_stage_ids)

    def test_helper_domain_shape_no_job(self):
        # White-box: the helper must produce a list-domain. With no job
        # and no current stage, it is just [('scope', '=', 'global')].
        Applicant = self.env['hr.applicant']
        domain = Applicant._visible_stages_domain(False, ())
        self.assertEqual(domain, [('scope', '=', 'global')])

    def test_helper_domain_shape_with_job_and_current(self):
        # White-box: with a job and a current stage id, R10 OR-branch
        # must be prepended.
        Applicant = self.env['hr.applicant']
        domain = Applicant._visible_stages_domain(self.job_a.id, (42,))
        self.assertEqual(domain[0], '|')
        self.assertEqual(domain[1], ('id', 'in', [42]))

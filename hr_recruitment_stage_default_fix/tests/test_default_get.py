# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestRecruitmentStageDefaultGet(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Job = cls.env['hr.job']
        cls.Stage = cls.env['hr.recruitment.stage']
        cls.job_a = cls.Job.create({'name': 'Test Vacancy A'})
        cls.job_b = cls.Job.create({'name': 'Test Vacancy B'})

    def test_stage_from_kanban_is_job_specific(self):
        """+Stage from inside a vacancy kanban → new stage is bound only to it."""
        defaults = self.Stage.with_context(
            default_job_id=self.job_a.id,
        ).default_get(['name', 'job_ids'])
        self.assertIn('job_ids', defaults)
        self.assertEqual(defaults['job_ids'], [(6, 0, [self.job_a.id])])

    def test_stage_from_configuration_is_global(self):
        """+Stage from Configuration → stage stays global (job_ids=[])."""
        defaults = self.Stage.default_get(['name', 'job_ids'])
        self.assertFalse(defaults.get('job_ids'))

    def test_explicit_default_job_ids_respected(self):
        """If the caller explicitly set default_job_ids — our override does not overwrite it."""
        explicit = [(6, 0, [self.job_a.id, self.job_b.id])]
        defaults = self.Stage.with_context(
            default_job_id=self.job_a.id,
            default_job_ids=explicit,
        ).default_get(['name', 'job_ids'])
        self.assertEqual(defaults.get('job_ids'), explicit)

    def test_mono_flag_escape_hatch(self):
        """hr_recruitment_stage_mono=True → stage remains global even with
        default_job_id (escape hatch for integrations that intentionally want
        the stock behaviour)."""
        defaults = self.Stage.with_context(
            default_job_id=self.job_a.id,
            hr_recruitment_stage_mono=True,
        ).default_get(['name', 'job_ids'])
        self.assertFalse(defaults.get('job_ids'))

    def test_full_create_flow_with_kanban_context(self):
        """End-to-end: creating a stage via create() with kanban context
        yields the correct job_ids (standard Odoo flow: default_get
        materialises defaults on create)."""
        stage = self.Stage.with_context(default_job_id=self.job_a.id).create({
            'name': 'Phone Screen',
        })
        self.assertEqual(stage.job_ids, self.job_a)
        self.assertNotIn(self.job_b, stage.job_ids)

    def test_existing_global_stages_unchanged(self):
        """Old global stages created before installing the module
        (simulated via the mono escape hatch) are not modified by our
        override — their job_ids stays empty."""
        old_stage = self.Stage.with_context(
            default_job_id=self.job_a.id,
            hr_recruitment_stage_mono=True,
        ).create({'name': 'Old Global Stage'})
        self.assertFalse(old_stage.job_ids)
        # Creating a new stage with kanban context does not touch the old one.
        new_stage = self.Stage.with_context(default_job_id=self.job_a.id).create({
            'name': 'New Specific Stage',
        })
        self.assertEqual(new_stage.job_ids, self.job_a)
        old_stage.invalidate_recordset()
        self.assertFalse(old_stage.job_ids)

    def test_default_get_without_job_ids_in_fields(self):
        """If fields does not include job_ids — we change nothing
        (protects other default_get calls from accidental side effects)."""
        defaults = self.Stage.with_context(
            default_job_id=self.job_a.id,
        ).default_get(['name'])
        self.assertNotIn('job_ids', defaults)

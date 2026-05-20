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
        """+Stage всередині kanban вакансії → нова стадія прив'язана тільки до неї."""
        defaults = self.Stage.with_context(
            default_job_id=self.job_a.id,
        ).default_get(['name', 'job_ids'])
        self.assertIn('job_ids', defaults)
        self.assertEqual(defaults['job_ids'], [(6, 0, [self.job_a.id])])

    def test_stage_from_configuration_is_global(self):
        """+Stage з Configuration → стадія глобальна (job_ids=[])."""
        defaults = self.Stage.default_get(['name', 'job_ids'])
        self.assertFalse(defaults.get('job_ids'))

    def test_explicit_default_job_ids_respected(self):
        """Якщо caller явно задав default_job_ids — наш override не перетирає."""
        explicit = [(6, 0, [self.job_a.id, self.job_b.id])]
        defaults = self.Stage.with_context(
            default_job_id=self.job_a.id,
            default_job_ids=explicit,
        ).default_get(['name', 'job_ids'])
        self.assertEqual(defaults.get('job_ids'), explicit)

    def test_mono_flag_escape_hatch(self):
        """hr_recruitment_stage_mono=True → стадія залишається глобальною
        навіть з default_job_id (escape hatch на випадок, коли інтеграція
        свідомо хоче стокову поведінку)."""
        defaults = self.Stage.with_context(
            default_job_id=self.job_a.id,
            hr_recruitment_stage_mono=True,
        ).default_get(['name', 'job_ids'])
        self.assertFalse(defaults.get('job_ids'))

    def test_full_create_flow_with_kanban_context(self):
        """End-to-end: створення стадії через create() з kanban-контекстом
        дає коректний job_ids (стандартний flow Odoo: default_get
        фіксує дефолти при create)."""
        stage = self.Stage.with_context(default_job_id=self.job_a.id).create({
            'name': 'Phone Screen',
        })
        self.assertEqual(stage.job_ids, self.job_a)
        self.assertNotIn(self.job_b, stage.job_ids)

    def test_existing_global_stages_unchanged(self):
        """Старі глобальні стадії, створені до встановлення модуля
        (симуляція через mono escape hatch), не модифікуються нашим
        override-ом — їх job_ids лишається порожнім."""
        old_stage = self.Stage.with_context(
            default_job_id=self.job_a.id,
            hr_recruitment_stage_mono=True,
        ).create({'name': 'Old Global Stage'})
        self.assertFalse(old_stage.job_ids)
        # Створення нової стадії з kanban-контекстом не чіпає стару.
        new_stage = self.Stage.with_context(default_job_id=self.job_a.id).create({
            'name': 'New Specific Stage',
        })
        self.assertEqual(new_stage.job_ids, self.job_a)
        old_stage.invalidate_recordset()
        self.assertFalse(old_stage.job_ids)

    def test_default_get_without_job_ids_in_fields(self):
        """Якщо fields не включає job_ids — нічого не змінюємо
        (захист від випадкового впливу на інші default_get-виклики)."""
        defaults = self.Stage.with_context(
            default_job_id=self.job_a.id,
        ).default_get(['name'])
        self.assertNotIn('job_ids', defaults)

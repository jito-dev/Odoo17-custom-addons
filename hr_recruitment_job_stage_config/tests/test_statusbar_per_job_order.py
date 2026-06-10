# -*- coding: utf-8 -*-
"""v17.0.1.0.12 — statusbar per-job order and fold.

Covers the two dimensions the v17.0.1.0.11 `allowed_stage_ids` domain
did NOT propagate to the applicant form statusbar:

* sequence ordering — `hr.recruitment.stage._order_to_sql` injects an
  ORDER BY `hr.job.stage.config.sequence` LEFT JOIN when the read
  context carries `applicant_stage_job_id`;
* fold — the computed `display_fold` field mirrors
  `hr.job.stage.config.fold` under the same context, otherwise falls
  back to the global `stage.fold`.

Stock visibility filtering (`allowed_stage_ids`) is covered separately
in test_stage_dropdown_domain.py.
"""
from odoo.tests.common import tagged

from .common import StageConfigTestCommon


@tagged('post_install', '-at_install')
class TestStatusbarPerJobOrder(StageConfigTestCommon):

    def test_search_orders_by_config_sequence_under_context(self):
        # Two globals with stage.sequence 10 and 20. Their config rows on
        # job_a swap the order via sequence 99 / 1. Without context we get
        # stock order (s_first then s_second); with context we get inverted.
        s_first = self._create_stage('JSC OrderA First', sequence=10)
        s_second = self._create_stage('JSC OrderA Second', sequence=20)

        cfg_first = self.Config.search([
            ('job_id', '=', self.job_a.id),
            ('stage_id', '=', s_first.id),
        ])
        cfg_second = self.Config.search([
            ('job_id', '=', self.job_a.id),
            ('stage_id', '=', s_second.id),
        ])
        self.assertTrue(cfg_first and cfg_second,
                        'Backfill must have produced both config rows.')
        cfg_first.sequence = 99
        cfg_second.sequence = 1

        stock_order = self.Stage.search([
            ('id', 'in', [s_first.id, s_second.id]),
        ])
        self.assertEqual(
            list(stock_order.ids), [s_first.id, s_second.id],
            'Without context the global stage.sequence (10, 20) must win.')

        per_job_order = self.Stage.with_context(
            applicant_stage_job_id=self.job_a.id,
        ).search([('id', 'in', [s_first.id, s_second.id])])
        self.assertEqual(
            list(per_job_order.ids), [s_second.id, s_first.id],
            'Under applicant_stage_job_id, config.sequence (1, 99) must '
            'reorder the result.')

    def test_search_falls_back_to_stage_sequence_when_no_config_row(self):
        # Two specific stages on job_b with NO config row on job_a. Searching
        # with applicant_stage_job_id=job_a returns them in stage.sequence
        # order (the LEFT JOIN yields NULL, NULLS LAST keeps tiebreaker).
        s_a = self._create_stage('JSC FB First', sequence=5,
                                  job_ids=[self.job_b])
        s_b = self._create_stage('JSC FB Second', sequence=15,
                                  job_ids=[self.job_b])

        result = self.Stage.with_context(
            applicant_stage_job_id=self.job_a.id,
        ).search([('id', 'in', [s_a.id, s_b.id])])
        self.assertEqual(
            list(result.ids), [s_a.id, s_b.id],
            'With NULL config.sequence the order must fall back to '
            'stage.sequence (5 before 15).')

    def test_search_ignores_context_for_explicit_order_argument(self):
        # Explicit order='name' must NOT be overridden. Protects callers that
        # know what they want (reports, exports).
        s_z = self._create_stage('JSC ExplicitZ', sequence=50)
        s_a = self._create_stage('JSC ExplicitA', sequence=51)

        result = self.Stage.with_context(
            applicant_stage_job_id=self.job_a.id,
        ).search([('id', 'in', [s_a.id, s_z.id])], order='name')
        self.assertEqual(
            list(result.ids), [s_a.id, s_z.id],
            'Explicit order=name must alphabetise — context override only '
            'kicks in when caller relies on default _order.')

    def test_display_fold_uses_config_fold_under_context(self):
        # Stage with global fold=False. Config row on job_a sets fold=True.
        # display_fold under context → True; without → False.
        stage = self._create_stage('JSC FoldGlobalOff', sequence=30, fold=False)
        cfg = self.Config.search([
            ('job_id', '=', self.job_a.id),
            ('stage_id', '=', stage.id),
        ])
        self.assertTrue(cfg, 'Backfill must have produced config row.')
        cfg.fold = True

        # Without context — stock stage.fold wins
        stage.invalidate_recordset(['display_fold'])
        self.assertFalse(
            stage.display_fold,
            'Without context display_fold must mirror stage.fold (False).')

        # With context — config.fold wins
        scoped = stage.with_context(applicant_stage_job_id=self.job_a.id)
        scoped.invalidate_recordset(['display_fold'])
        self.assertTrue(
            scoped.display_fold,
            'Under applicant_stage_job_id, config.fold (True) must win.')

    def test_display_fold_falls_back_to_stage_when_no_config_row(self):
        # Specific stage on job_b with no config row on job_a. Stage fold=True.
        # display_fold under job_a context must still return True (fallback).
        stage = self._create_stage(
            'JSC FoldFallback', sequence=40, job_ids=[self.job_b], fold=True)
        scoped = stage.with_context(applicant_stage_job_id=self.job_a.id)
        self.assertTrue(
            scoped.display_fold,
            'Missing config row → display_fold must fall back to stage.fold.')

    def test_display_fold_handles_invalid_context_value(self):
        # Defensive: a stringified or garbage applicant_stage_job_id must
        # neither crash nor poison the result; we just fall back to stock.
        stage = self._create_stage('JSC FoldInvalidCtx', sequence=60, fold=True)
        result = stage.with_context(
            applicant_stage_job_id='not-an-int',
        ).display_fold
        self.assertTrue(
            result, 'Invalid context job id must degrade to stage.fold.')

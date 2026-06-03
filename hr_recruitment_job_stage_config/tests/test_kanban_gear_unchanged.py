# -*- coding: utf-8 -*-
"""PR 2.5: frozen-scope smoke for the kanban "+Stage" / gear path.

PR 2.5 explicitly does not touch the kanban gear over a stage column.
This test asserts that ``hr.recruitment.stage`` still loads the stock
form when opened via the kanban gear (i.e. no module of ours has
inherited or replaced that view in a way that would change the
recruiter's create-stage flow).
"""
from odoo.tests.common import tagged

from .common import StageConfigTestCommon


@tagged('post_install', '-at_install')
class TestKanbanGearUnchanged(StageConfigTestCommon):
    def test_stage_form_view_loads_stock(self):
        view = self.env.ref('hr_recruitment.hr_recruitment_stage_form', raise_if_not_found=False)
        self.assertTrue(view, 'Stock stage form view must be present')
        # Loading the view must not raise — covers inheritance health.
        # `get_view()` returns dict keyed by 'arch'/'model'/'id'/... in
        # Odoo 17 (no 'type' key); the view record itself carries the
        # view type, so assert via the view record.
        fields_view = self.Stage.with_context(default_job_id=self.job_a.id) \
            .get_view(view_id=view.id, view_type='form')
        self.assertEqual(view.type, 'form')
        self.assertEqual(fields_view['model'], 'hr.recruitment.stage')

    def test_create_stage_with_default_job_id_attaches_job(self):
        # This mirrors the kanban gear "+Stage" flow, which is owned by
        # hr_recruitment_stage_default_fix / foundation. PR 2.5 must
        # leave it intact.
        stage = self.Stage.with_context(default_job_id=self.job_a.id) \
            .create({'name': 'PR 2.5 Kanban Gear Smoke'})
        self.assertIn(self.job_a, stage.job_ids)

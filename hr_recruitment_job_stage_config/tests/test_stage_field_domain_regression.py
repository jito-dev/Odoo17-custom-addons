# -*- coding: utf-8 -*-
"""v17.0.1.0.11 — regression guard: stage_id field must carry the
allowed_stage_ids domain on every applicant view.

If a future override accidentally drops our domain (or restores the
stock one referencing job_ids), this assertion catches it before users
see hidden stages back in the dropdown.
"""
from odoo.tests.common import tagged

from .common import StageConfigTestCommon


@tagged('post_install', '-at_install')
class TestStageFieldDomainRegression(StageConfigTestCommon):

    def test_field_definition_carries_allowed_stage_ids_domain(self):
        # The Field object's domain attribute is set by our re-declaration
        # in hr_recruitment_job_stage_config.models.hr_applicant. If a later
        # _inherit drops it, this test fails.
        field = self.Applicant._fields['stage_id']
        self.assertIn(
            'allowed_stage_ids', str(field.domain),
            "stage_id domain must reference allowed_stage_ids "
            "(got: %r)" % (field.domain,))

    def test_allowed_stage_ids_field_exists_as_non_stored_m2m(self):
        field = self.Applicant._fields.get('allowed_stage_ids')
        self.assertIsNotNone(field, "allowed_stage_ids must be declared")
        self.assertEqual(field.type, 'many2many')
        self.assertFalse(field.store,
                         "allowed_stage_ids must be non-stored (computed)")
        self.assertEqual(field.comodel_name, 'hr.recruitment.stage')

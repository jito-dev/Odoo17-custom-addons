# -*- coding: utf-8 -*-
"""Sub-module-side mirror of the foundation regression test — confirms that,
once hr_recruitment_call_stage is installed, _has_payload now recognises the
new fields as payload (truthy is_call_stage means the row survives a scope
flip).
"""
from odoo.tests import tagged

from .common import CallStageTestCommon


@tagged('post_install', '-at_install')
class TestPayloadFieldsExtended(CallStageTestCommon):
    def test_is_call_stage_counts_as_payload(self):
        cfg = self._get_config(self.job_designer, self.stage_call)
        # No payload yet.
        self.assertFalse(cfg._has_payload())
        cfg.write({
            'is_call_stage': True,
            'booking_appointment_type_id': self.appt_hr_call.id,
        })
        cfg.invalidate_recordset()
        self.assertTrue(cfg._has_payload(),
                        "is_call_stage=True must count as payload")

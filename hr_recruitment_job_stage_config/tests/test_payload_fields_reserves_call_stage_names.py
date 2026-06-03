# -*- coding: utf-8 -*-
"""v17.0.1.0.13 regression — _PAYLOAD_FIELDS reserves the call-stage names
(is_call_stage, booking_appointment_type_id, call_booked_stage_id).

The names are declared by the sub-module hr_recruitment_call_stage but
recognised here so that scope-flip cleanup cannot silently delete config
rows whose only meaningful state lives in those columns. When the sub-
module is not installed, _has_payload must skip them defensively without
crashing.
"""
from odoo.addons.hr_recruitment_job_stage_config.models.hr_job_stage_config import (
    _PAYLOAD_FIELDS,
)

from .common import StageConfigTestCommon


class TestPayloadFieldsReservesCallStageNames(StageConfigTestCommon):
    def test_reserved_names_present(self):
        for name in (
            'is_call_stage',
            'booking_appointment_type_id',
            'call_booked_stage_id',
        ):
            self.assertIn(
                name, _PAYLOAD_FIELDS,
                msg=f"{name!r} must stay in _PAYLOAD_FIELDS — see "
                    "docs/recruitment_calendar_booking.md §3.2 and "
                    "GUIDANCE v17.0.1.0.13. Removing it lets scope-flip "
                    "silently delete call-stage config rows.",
            )

    def test_has_payload_handles_missing_fields(self):
        # When the sub-module is not installed, the names above are not in
        # self._fields. _has_payload must skip them rather than raise.
        stage = self._create_stage('Reservation guard stage', job_ids=[self.job_a])
        config = self.Config.search([
            ('job_id', '=', self.job_a.id),
            ('stage_id', '=', stage.id),
        ], limit=1)
        self.assertTrue(config, "Auto-row should exist for (job_a, new stage)")
        # No override payload set anywhere => row is "auto" => safe to drop.
        # The point of this test is that the call does not raise even when
        # is_call_stage / booking_appointment_type_id / call_booked_stage_id
        # are not declared on the model.
        self.assertFalse(config._has_payload())

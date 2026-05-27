# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import CallStageTestCommon


@tagged('post_install', '-at_install')
class TestCallStageConfig(CallStageTestCommon):
    def test_constrains_call_stage_requires_appointment_type(self):
        cfg = self._get_config(self.job_designer, self.stage_call)
        with self.assertRaises(ValidationError):
            cfg.is_call_stage = True

    def test_first_tick_links_call_booked_for_job(self):
        cfg = self._get_config(self.job_designer, self.stage_call)
        cfg.write({
            'is_call_stage': True,
            'booking_appointment_type_id': self.appt_hr_call.id,
        })
        self.assertEqual(cfg.call_booked_stage_id, self.stage_call_booked)
        self.assertIn(self.job_designer, self.stage_call_booked.job_ids,
                      "Call Booked must be linked to the job after first tick")
        # Foundation auto-creates the (job, Call Booked) config row.
        cb_cfg = self._get_config(self.job_designer, self.stage_call_booked)
        self.assertTrue(cb_cfg)
        self.assertTrue(cb_cfg.visible)

    def test_second_tick_idempotent(self):
        cfg_d = self._get_config(self.job_designer, self.stage_call)
        cfg_e = self._get_config(self.job_engineer, self.stage_call)
        cfg_d.write({
            'is_call_stage': True,
            'booking_appointment_type_id': self.appt_hr_call.id,
        })
        cfg_e.write({
            'is_call_stage': True,
            'booking_appointment_type_id': self.appt_tech_call.id,
        })
        # Both jobs end up linked, no duplicate config rows.
        self.assertEqual(self.stage_call_booked.job_ids,
                         self.job_designer + self.job_engineer)
        rows = self.Config.search([
            ('stage_id', '=', self.stage_call_booked.id),
            ('job_id', 'in', (self.job_designer + self.job_engineer).ids),
        ])
        self.assertEqual(len(rows), 2)

    def test_untick_clears_state_without_unlinking_job(self):
        cfg = self._get_config(self.job_designer, self.stage_call)
        cfg.write({
            'is_call_stage': True,
            'booking_appointment_type_id': self.appt_hr_call.id,
        })
        # Sanity
        self.assertIn(self.job_designer, self.stage_call_booked.job_ids)

        cfg.write({
            'is_call_stage': False,
            'booking_appointment_type_id': False,
        })
        # Per §4.2 of the design: we DO NOT remove the job from
        # stage_call_booked.job_ids. The config row stays.
        self.assertIn(self.job_designer, self.stage_call_booked.job_ids)

    def test_scope_flip_keeps_call_stage_row(self):
        # Regression for _PAYLOAD_FIELDS extension (foundation v17.0.1.0.13).
        # A stage that is specific-to-this-job, with is_call_stage on, must
        # survive a scope flip back to global.
        cfg = self._get_config(self.job_designer, self.stage_call)
        cfg.write({
            'is_call_stage': True,
            'booking_appointment_type_id': self.appt_hr_call.id,
        })
        # Flip the stage back to global.
        self.stage_call.scope = 'global'
        survivor = self._get_config(self.job_designer, self.stage_call)
        self.assertTrue(survivor,
                        "Call-stage config row was deleted on scope flip — "
                        "_PAYLOAD_FIELDS regression.")
        self.assertTrue(survivor.is_call_stage)
        self.assertEqual(
            survivor.booking_appointment_type_id, self.appt_hr_call)

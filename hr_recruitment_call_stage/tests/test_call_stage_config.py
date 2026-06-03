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

    def test_first_tick_mints_paired_call_booked_for_job(self):
        # Etap 8 (v17.0.7.0.0): first tick mints a per-(job, stage) paired
        # Call Booked stage — NOT the legacy global stage_call_booked.
        cfg = self._get_config(self.job_designer, self.stage_call)
        cfg.write({
            'is_call_stage': True,
            'booking_appointment_type_id': self.appt_hr_call.id,
        })
        paired = cfg.call_booked_stage_id
        self.assertTrue(paired, "First tick must mint a paired Call Booked stage")
        self.assertNotEqual(paired, self.stage_call_booked,
                            "Paired stage is per-config, not the legacy global")
        # Name order flipped + first-letter capitalised (v17.0.10.0.0).
        self.assertEqual(paired.name, 'Call to schedule CS — Call Booked')
        self.assertIn(self.job_designer, paired.job_ids,
                      "Paired stage must be scoped to the job after first tick")
        # Foundation auto-creates the (job, paired) config row, visible.
        cb_cfg = self._get_config(self.job_designer, paired)
        self.assertTrue(cb_cfg)
        self.assertTrue(cb_cfg.visible)

    def test_each_config_gets_its_own_paired_stage_and_sync_is_idempotent(self):
        # Two Call Stages (one per job) each own a DISTINCT paired stage,
        # scoped to their own job — no shared global bucket. Re-running the
        # sync on an already-paired config mints nothing (idempotent guard).
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
        paired_d = cfg_d.call_booked_stage_id
        paired_e = cfg_e.call_booked_stage_id
        self.assertTrue(paired_d and paired_e)
        self.assertNotEqual(paired_d, paired_e,
                            "Each config must own a distinct paired stage")
        self.assertEqual(paired_d.job_ids, self.job_designer)
        self.assertEqual(paired_e.job_ids, self.job_engineer)
        # Idempotent: re-running the sync reuses the existing paired stage.
        before = self.Stage.search_count([])
        cfg_d._sync_call_booked_membership()
        cfg_d.invalidate_recordset(['call_booked_stage_id'])
        self.assertEqual(cfg_d.call_booked_stage_id, paired_d,
                         "Re-sync must reuse the existing paired stage")
        self.assertEqual(self.Stage.search_count([]), before,
                         "Re-sync must not mint a duplicate paired stage")

    def test_untick_keeps_paired_stage_linked_to_job(self):
        cfg = self._get_config(self.job_designer, self.stage_call)
        cfg.write({
            'is_call_stage': True,
            'booking_appointment_type_id': self.appt_hr_call.id,
        })
        paired = cfg.call_booked_stage_id
        self.assertIn(self.job_designer, paired.job_ids)

        cfg.write({
            'is_call_stage': False,
            'booking_appointment_type_id': False,
        })
        # Untick neither unlinks the paired stage from the job nor clears the
        # back-reference: candidate history on the paired stage is preserved,
        # and re-ticking reuses it (archival happens only on config unlink).
        self.assertIn(self.job_designer, paired.job_ids)
        self.assertEqual(cfg.call_booked_stage_id, paired)

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

# -*- coding: utf-8 -*-
"""v17.0.1.1.0 — On-hold in stage."""
from odoo.tests import tagged

from .common import StageConfigTestCommon
from odoo.addons.hr_recruitment_job_stage_config.models.hr_applicant_on_hold import (
    _ON_HOLD_ACTIVITY_SUMMARY,
)


@tagged('post_install', '-at_install')
class TestOnHold(StageConfigTestCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.stage_1 = cls._create_stage('Screen JSC', sequence=10,
                                        job_ids=[cls.job_a])
        cls.stage_2 = cls._create_stage('Interview JSC', sequence=20,
                                        job_ids=[cls.job_a])

    def _activities(self, applicant):
        return self.env['mail.activity'].search([
            ('res_model', '=', 'hr.applicant'),
            ('res_id', '=', applicant.id),
            ('summary', '=', _ON_HOLD_ACTIVITY_SUMMARY),
        ])

    def test_put_on_hold_keeps_stage(self):
        applicant = self._create_applicant('Anna JSC', self.job_a, self.stage_1)
        applicant.action_put_on_hold()
        self.assertTrue(applicant.on_hold)
        self.assertEqual(applicant.stage_id, self.stage_1,
            "putting on hold must NOT move the candidate")
        self.assertTrue(applicant.on_hold_date)
        self.assertEqual(applicant.on_hold_by_id, self.env.user)

    def test_resume_clears_flag(self):
        applicant = self._create_applicant('Bob JSC', self.job_a, self.stage_1)
        applicant.action_put_on_hold()
        applicant.on_hold_reason = 'Waiting for budget'
        applicant.action_resume()
        self.assertFalse(applicant.on_hold)
        self.assertFalse(applicant.on_hold_date)
        self.assertFalse(applicant.on_hold_by_id)
        self.assertFalse(applicant.on_hold_reason)

    def test_stage_move_auto_resumes(self):
        applicant = self._create_applicant('Cara JSC', self.job_a, self.stage_1)
        applicant.action_put_on_hold()
        self.assertTrue(applicant.on_hold)
        applicant.stage_id = self.stage_2.id
        self.assertFalse(applicant.on_hold,
            "moving to another stage must auto-resume")
        self.assertEqual(applicant.stage_id, self.stage_2)

    def test_same_stage_rewrite_keeps_hold(self):
        applicant = self._create_applicant('Dan JSC', self.job_a, self.stage_1)
        applicant.action_put_on_hold()
        # Writing stage_id to the SAME stage must not resume.
        applicant.write({'stage_id': self.stage_1.id})
        self.assertTrue(applicant.on_hold,
            "a no-op stage rewrite must not clear the hold")

    def test_until_schedules_and_clears_activity(self):
        applicant = self._create_applicant('Eve JSC', self.job_a, self.stage_1)
        applicant.action_put_on_hold()
        self.assertFalse(self._activities(applicant),
            "no reminder until an until-date is set")
        applicant.on_hold_until = '2099-01-01'
        acts = self._activities(applicant)
        self.assertEqual(len(acts), 1, "until-date must schedule one reminder")
        self.assertEqual(str(acts.date_deadline), '2099-01-01')
        # Resuming removes the reminder.
        applicant.action_resume()
        self.assertFalse(self._activities(applicant),
            "resuming must remove the reminder activity")

    def test_until_reminder_is_idempotent(self):
        applicant = self._create_applicant('Finn JSC', self.job_a, self.stage_1)
        applicant.action_put_on_hold()
        applicant.on_hold_until = '2099-01-01'
        applicant.on_hold_until = '2099-02-02'
        acts = self._activities(applicant)
        self.assertEqual(len(acts), 1,
            "changing the until-date must update, not duplicate, the reminder")
        self.assertEqual(str(acts.date_deadline), '2099-02-02')

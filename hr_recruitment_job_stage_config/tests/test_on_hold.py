# -*- coding: utf-8 -*-
"""v17.0.1.3.0 — On-hold in stage (open-ended; no revisit date)."""
from odoo.tests import tagged

from .common import StageConfigTestCommon


@tagged('post_install', '-at_install')
class TestOnHold(StageConfigTestCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.stage_1 = cls._create_stage('Screen JSC', sequence=10,
                                        job_ids=[cls.job_a])
        cls.stage_2 = cls._create_stage('Interview JSC', sequence=20,
                                        job_ids=[cls.job_a])

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

    def test_on_hold_edit_fields_are_tracked(self):
        # Recruiter edits to the flag / reason are logged to the candidate
        # chatter via native field tracking.
        fields_ = self.env['hr.applicant']._fields
        self.assertTrue(fields_['on_hold'].tracking,
            "on_hold changes must be tracked in the chatter")
        self.assertTrue(fields_['on_hold_reason'].tracking,
            "on_hold_reason edits must be tracked in the chatter")

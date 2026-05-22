# -*- coding: utf-8 -*-
from .common import StageConfigTestCommon


class TestComputeStageWithHidden(StageConfigTestCommon):
    """R10 — new applicants must never land on a stage hidden for their job."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Three global stages with explicit sequence
        cls.s1 = cls._create_stage('JSC compute first', sequence=10)
        cls.s2 = cls._create_stage('JSC compute middle', sequence=20)
        cls.s3 = cls._create_stage('JSC compute last', sequence=30)

    def test_new_applicant_lands_on_first_visible_stage(self):
        # Hide the natural first stage in job A
        self.Config.create({
            'job_id': self.job_a.id,
            'stage_id': self.s1.id,
            'visible': False,
        })
        applicant = self.Applicant.create({
            'partner_name': 'JSC r10 newcomer',
            'job_id': self.job_a.id,
        })
        self.assertEqual(applicant.stage_id, self.s2,
            "new applicant must skip hidden first stage and land on s2")

    def test_per_job_sequence_override_drives_first_stage(self):
        """If config.sequence reorders stages, the new applicant's default
        stage follows that order, not the global stage.sequence."""
        # In job A, reorder: s3=5 (becomes first), s1=10, s2=20
        self.Config.create({
            'job_id': self.job_a.id,
            'stage_id': self.s3.id,
            'sequence': 5,
        })
        applicant = self.Applicant.create({
            'partner_name': 'JSC r10 reordered',
            'job_id': self.job_a.id,
        })
        self.assertEqual(applicant.stage_id, self.s3,
            "per-job sequence override must drive default stage")

    def test_no_visible_stages_gives_no_stage(self):
        # Hide all stages for job_b
        for st in (self.s1, self.s2, self.s3):
            self.Config.create({
                'job_id': self.job_b.id,
                'stage_id': st.id,
                'visible': False,
            })
        applicant = self.Applicant.create({
            'partner_name': 'JSC r10 no-stages',
            'job_id': self.job_b.id,
        })
        self.assertFalse(applicant.stage_id,
            "with no visible stage, the applicant gets stage_id=False")

    def test_existing_stage_id_is_not_overwritten(self):
        """Once a stage is set, _compute_stage must not change it (mirrors
        stock behaviour: compute only fills when stage_id is empty)."""
        # Hide s2; then create applicant directly on s2 — compute must not
        # bump it forward.
        self.Config.create({
            'job_id': self.job_a.id,
            'stage_id': self.s2.id,
            'visible': False,
        })
        applicant = self.Applicant.create({
            'partner_name': 'JSC r10 sticky',
            'job_id': self.job_a.id,
            'stage_id': self.s2.id,
        })
        self.assertEqual(applicant.stage_id, self.s2)

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
        # `_compute_stage` walks every stage that is visible for the
        # applicant's job. In a dirty dev DB (or in production with prior
        # canonical stages), other globals exist and would race our fixtures
        # for the "first visible" slot. Pin the baseline: force every other
        # global stage to hidden=False on both jobs via a config row, so the
        # only candidates for _compute_stage are s1/s2/s3. The TransactionCase
        # rollback restores everything when the class finishes.
        fixture_ids = (cls.s1 + cls.s2 + cls.s3).ids
        other_globals = cls.Stage.search([
            ('scope', '=', 'global'),
            ('id', 'not in', fixture_ids),
        ])
        for job in (cls.job_a, cls.job_b):
            for stage in other_globals:
                cls._get_or_create_config(job, stage, visible=False)

    def test_new_applicant_lands_on_first_visible_stage(self):
        # Make s1 visible (auto-row may be visible=False for non-canonical
        # names) and explicitly hide s1 in job A's config.
        self._get_or_create_config(self.job_a, self.s2, visible=True)
        self._get_or_create_config(self.job_a, self.s3, visible=True)
        self._get_or_create_config(self.job_a, self.s1, visible=False)
        applicant = self.Applicant.create({
            'name': 'JSC r10 newcomer',
            'partner_name': 'JSC r10 newcomer',
            'job_id': self.job_a.id,
        })
        self.assertEqual(applicant.stage_id, self.s2,
            "new applicant must skip hidden first stage and land on s2")

    def test_per_job_sequence_override_drives_first_stage(self):
        """If config.sequence reorders stages, the new applicant's default
        stage follows that order, not the global stage.sequence."""
        # All three visible; in job A, reorder: s3=5 (becomes first), defaults
        # for s1 and s2 stay at stage.sequence (10/20).
        self._get_or_create_config(self.job_a, self.s1, visible=True)
        self._get_or_create_config(self.job_a, self.s2, visible=True)
        self._get_or_create_config(self.job_a, self.s3, visible=True, sequence=5)
        applicant = self.Applicant.create({
            'name': 'JSC r10 reordered',
            'partner_name': 'JSC r10 reordered',
            'job_id': self.job_a.id,
        })
        self.assertEqual(applicant.stage_id, self.s3,
            "per-job sequence override must drive default stage")

    def test_no_visible_stages_gives_no_stage(self):
        # Hide all visible stages for job_b — including any pre-existing
        # canonical stages auto-seeded with visible=True at module install.
        all_for_b = self.Config.search([('job_id', '=', self.job_b.id)])
        all_for_b.write({'visible': False})
        for st in (self.s1, self.s2, self.s3):
            self._get_or_create_config(self.job_b, st, visible=False)
        applicant = self.Applicant.create({
            'name': 'JSC r10 no-stages',
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
        self._get_or_create_config(self.job_a, self.s2, visible=False)
        applicant = self.Applicant.create({
            'name': 'JSC r10 sticky',
            'partner_name': 'JSC r10 sticky',
            'job_id': self.job_a.id,
            'stage_id': self.s2.id,
        })
        self.assertEqual(applicant.stage_id, self.s2)

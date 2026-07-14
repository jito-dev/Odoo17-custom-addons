# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestApplicantOrigin(TransactionCase):
    """The computed `applicant_origin` ("Candidate Source") classifies how a
    record entered the system, independently from the marketing UTM source_id."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Applicant = cls.env['hr.applicant']
        cls.job = cls.env['hr.job'].create({'name': 'Tracker Test Job'})

    def test_manual_candidate_origin(self):
        """A plainly created candidate (no tracker, no Djinni id) is Manual."""
        app = self.Applicant.create({'name': 'Walk-in'})
        self.assertEqual(app.applicant_origin, 'manual')

    def test_tracking_link_candidate_origin(self):
        """A candidate carrying a tracker_id is classified as Tracking Link."""
        tracker = self.env['hr.recruitment.tracker'].create({
            'name': 'T1',
            'target_url': 'https://example.com/jobs/1',
            'job_id': self.job.id,
        })
        app = self.Applicant.create({'name': 'Via link', 'tracker_id': tracker.id})
        self.assertEqual(app.applicant_origin, 'tracking_link')

    def test_djinni_candidate_origin(self):
        """A candidate carrying a Djinni id is classified as Djinni Integration.

        Skipped when hr_djinni is not installed — the classification is a *soft*
        dependency (the compute guards on the field's presence), so the module
        must keep working without it.
        """
        if 'djinni_ref' not in self.Applicant._fields:
            self.skipTest('hr_djinni not installed')
        app = self.Applicant.create({'name': 'From Djinni', 'djinni_ref': '999001'})
        self.assertEqual(app.applicant_origin, 'djinni')

    def test_tracker_wins_over_djinni(self):
        """If somehow both signals are present, the tracking link takes priority
        (matches the if/elif order in the compute)."""
        if 'djinni_ref' not in self.Applicant._fields:
            self.skipTest('hr_djinni not installed')
        tracker = self.env['hr.recruitment.tracker'].create({
            'name': 'T2',
            'target_url': 'https://example.com/jobs/2',
            'job_id': self.job.id,
        })
        app = self.Applicant.create({
            'name': 'Both', 'tracker_id': tracker.id, 'djinni_ref': '999002',
        })
        self.assertEqual(app.applicant_origin, 'tracking_link')

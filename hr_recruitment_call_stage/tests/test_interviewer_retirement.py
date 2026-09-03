# -*- coding: utf-8 -*-
"""v17.0.28.0.0 — the migration that retires the Interviewer field.

The field is gone; what it used to *do* on a given stage may not be. A stage
that pinned a strict subset of its appointment type's staff was excluding
somebody on purpose, and an upgrade must not quietly let that person back in
front of candidates. Such a stage is given an appointment type of its own.

Everything else is left exactly as it is — including pins that had already
stopped working, because restoring an intent the system abandoned months ago
would be its own silent behaviour change.

The migration is loaded from its file: `migrations/` is not an importable
package.
"""
import importlib.util
from pathlib import Path

from odoo.tests.common import tagged

from .common import CallStageTestCommon

_MIGRATION = (Path(__file__).resolve().parent.parent
              / 'migrations' / '17.0.28.0.0' / 'post-migrate.py')
_REL = 'hr_job_stage_config_call_staff_user_rel'


def _load_migration():
    spec = importlib.util.spec_from_file_location('cs_retire_pins', _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@tagged('post_install', '-at_install')
class TestInterviewerRetirementMigration(CallStageTestCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.migration = _load_migration()
        cls.ann = cls.env['res.users'].create({
            'name': 'Ann Retire', 'login': 'cs_ann_retire',
            'email': 'cs_ann_retire@example.com'})
        cls.bob = cls.env['res.users'].create({
            'name': 'Bob Retire', 'login': 'cs_bob_retire',
            'email': 'cs_bob_retire@example.com'})
        cls.appt_hr_call.staff_user_ids = [(6, 0, [cls.ann.id, cls.bob.id])]

    def setUp(self):
        super().setUp()
        self.cfg = self._get_config(self.job_designer, self.stage_call)
        self.cfg.write({
            'is_call_stage': True,
            'booking_appointment_type_id': self.appt_hr_call.id,
        })

    def _pin(self, users):
        """Write straight into the retired many2many table, as prod carries it."""
        for user in users:
            self.env.cr.execute(
                "INSERT INTO %s (config_id, user_id) VALUES (%%s, %%s) "
                "ON CONFLICT DO NOTHING" % _REL, (self.cfg.id, user.id))

    def _run(self):
        self.migration.migrate(self.env.cr, '17.0.27.2.1')
        self.cfg.invalidate_recordset()

    def _types(self):
        return self.env['appointment.type'].with_context(
            active_test=False).search_count([])

    def test_pin_matching_the_whole_staff_changes_nothing(self):
        self._pin(self.ann | self.bob)
        before = self._types()
        self._run()
        self.assertEqual(self._types(), before,
                         "A pin that excluded nobody needs no type of its own")
        self.assertEqual(
            self.cfg.booking_appointment_type_id, self.appt_hr_call)

    def test_narrowing_pin_gets_a_dedicated_type(self):
        self._pin(self.ann)
        self._run()
        created = self.cfg.booking_appointment_type_id
        self.assertNotEqual(
            created, self.appt_hr_call,
            "Excluding Bob must survive the upgrade, not be dropped")
        self.assertEqual(created.staff_user_ids, self.ann)
        self.assertTrue(created.active)
        self.assertEqual(
            self.appt_hr_call.staff_user_ids, self.ann | self.bob,
            "The shared type must come out untouched — other stages book it")
        if 'cover_properties' in created._fields:
            # A type created without them renders a 500 on its website page:
            # `website.record_cover` does json.loads(cover_properties) and
            # False is not JSON. It happened, because a post-migrate runs while
            # the registry is still loading and the field may be absent.
            self.assertTrue(
                created.cover_properties,
                "A dedicated type must carry the website cover properties")

    def test_narrowing_pin_takes_live_invites_with_it(self):
        applicant = self._make_applicant(
            'Retire Candidate', self.job_designer, self.stage_call)
        invite = applicant._get_or_create_booking_invite(self.appt_hr_call)
        self.assertEqual(invite.appointment_type_ids, self.appt_hr_call)

        self._pin(self.ann)
        self._run()
        created = self.cfg.booking_appointment_type_id
        invite.invalidate_recordset(['appointment_type_ids'])
        self.assertEqual(
            invite.appointment_type_ids, created,
            "Left on the old type, this candidate would read as 'no link' in "
            "the cockpit and be sent a second one.")
        applicant.invalidate_recordset(['booking_url', 'call_status'])
        self.assertTrue(
            applicant.booking_url,
            "The candidate's existing link must keep resolving.")

    def test_pin_that_had_stopped_working_is_left_alone(self):
        """Somebody was removed from the type: today the stage books everyone."""
        outsider = self.env['res.users'].create({
            'name': 'Gone Already', 'login': 'cs_gone_already',
            'email': 'cs_gone@example.com'})
        self._pin(outsider)
        before = self._types()
        self._run()
        self.assertEqual(self._types(), before)
        self.assertEqual(
            self.cfg.booking_appointment_type_id, self.appt_hr_call,
            "Preserve what happens today, not an intent the system dropped")

    def test_archived_pin_is_left_alone(self):
        self._pin(self.ann)
        self.ann.active = False
        before = self._types()
        self._run()
        self.assertEqual(self._types(), before)

    def test_running_twice_creates_nothing_extra(self):
        self._pin(self.ann)
        self._run()
        created = self.cfg.booking_appointment_type_id
        after_first = self._types()
        # The pins table is untouched by the migration, so a re-run sees the
        # same rows — and must now find the stage already narrowed correctly.
        self._run()
        self.assertEqual(self._types(), after_first,
                         "A second pass must not split the stage again")
        self.assertEqual(self.cfg.booking_appointment_type_id, created)

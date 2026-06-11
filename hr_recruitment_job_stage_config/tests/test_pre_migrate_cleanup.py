# -*- coding: utf-8 -*-
"""PR 2.5: pre-migrate cleanup of broken mail_template_id FKs.

The 17.0.1.0.10 pre-migrate script NULLs out
``hr_job_stage_config.mail_template_id`` rows where the referenced
``mail.template`` has ``model_id IS NULL`` or ``model != 'hr.applicant'``,
and logs each to ``ir.logging``.

This test invokes the migrate() function directly with a hand-crafted
broken row and asserts both effects.
"""
from odoo.tests.common import tagged

from .common import StageConfigTestCommon


@tagged('post_install', '-at_install')
class TestPreMigrateCleanup(StageConfigTestCommon):
    """We can't import the migration via Odoo's normal module path because
    versioned migrations live in ``migrations/17.0.1.0.10/pre-migrate.py``
    (filenames with dots and dashes aren't python modules). So we load
    the file by path."""

    def setUp(self):
        super().setUp()
        import importlib.util
        import os
        path = os.path.join(
            os.path.dirname(__file__), '..', 'migrations', '17.0.1.0.10',
            'pre-migrate.py',
        )
        spec = importlib.util.spec_from_file_location('pr_2_5_premigrate', path)
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)

        self.stage = self._create_stage('PR 2.5 PreMig Stage')
        self.applicant_model_id = self.env['ir.model']._get_id('hr.applicant')

        # Valid template — must be left alone.
        self.tmpl_ok = self.MailTemplate.create({
            'name': 'PR 2.5 PreMig OK',
            'model_id': self.applicant_model_id,
            'subject': 'X', 'body_html': '<p>X</p>',
        })
        # Broken template — model_id will be NULLed via raw SQL below.
        self.tmpl_broken = self.MailTemplate.create({
            'name': 'PR 2.5 PreMig Broken',
            'model_id': self.applicant_model_id,
            'subject': 'X', 'body_html': '<p>X</p>',
        })

        # Stage was just created globally → auto-create already produced a
        # row for every existing job (visible=False). Reuse that row and add
        # the OK template via write() to keep the unique constraint happy.
        self.config_ok = self._get_or_create_config(
            self.job_a, self.stage, mail_template_id=self.tmpl_ok.id)

        # Build the broken-FK fixture safely. The old approach used
        # ``invalidate_recordset(flush=False)`` to keep the cached ORM values
        # from overwriting our raw-SQL edits — but that leaves the field in the
        # "to-write" set, and a later ``flush=True`` then asserts in Odoo 17's
        # ``_flush`` ("Could not find all values ... to flush"). Instead:
        #   1. flush_all() persists every pending ORM write to the DB and clears
        #      the dirty/to-write tracking, so nothing is left to flush.
        #   2. raw SQL injects the broken state (bypassing our @api.constrains,
        #      simulating legacy rows created before the constraint existed).
        #   3. invalidate_all() drops the now-stale cache so reads honour the DB.
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE mail_template SET model_id = NULL WHERE id = %s",
            (self.tmpl_broken.id,),
        )
        self.env.cr.execute(
            "UPDATE hr_job_stage_config SET mail_template_id = %s "
            "WHERE id = %s",
            (self.tmpl_broken.id, self.config_ok.id),
        )
        self.env.invalidate_all()

    def test_broken_fk_is_cleared(self):
        self.mod.migrate(self.env.cr, None)
        self.env.invalidate_all()
        self.assertFalse(self.config_ok.mail_template_id)

    def test_log_row_inserted(self):
        self.env.cr.execute(
            "SELECT COUNT(*) FROM ir_logging "
            "WHERE name = 'hr_recruitment_job_stage_config.pre_migrate'"
        )
        before = self.env.cr.fetchone()[0]
        self.mod.migrate(self.env.cr, None)
        self.env.cr.execute(
            "SELECT COUNT(*) FROM ir_logging "
            "WHERE name = 'hr_recruitment_job_stage_config.pre_migrate'"
        )
        after = self.env.cr.fetchone()[0]
        self.assertGreater(after, before)

    def test_idempotent_rerun(self):
        self.mod.migrate(self.env.cr, None)
        # Second call should NULL nothing (no broken rows left).
        self.env.cr.execute(
            "SELECT COUNT(*) FROM ir_logging "
            "WHERE name = 'hr_recruitment_job_stage_config.pre_migrate'"
        )
        before = self.env.cr.fetchone()[0]
        self.mod.migrate(self.env.cr, None)
        self.env.cr.execute(
            "SELECT COUNT(*) FROM ir_logging "
            "WHERE name = 'hr_recruitment_job_stage_config.pre_migrate'"
        )
        after = self.env.cr.fetchone()[0]
        self.assertEqual(after, before)

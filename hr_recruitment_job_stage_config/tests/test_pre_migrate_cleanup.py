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
        # Broken template — model_id will be NULLed via raw SQL.
        self.tmpl_broken = self.MailTemplate.create({
            'name': 'PR 2.5 PreMig Broken',
            'model_id': self.applicant_model_id,
            'subject': 'X', 'body_html': '<p>X</p>',
        })
        self.env.cr.execute(
            "UPDATE mail_template SET model_id = NULL WHERE id = %s",
            (self.tmpl_broken.id,),
        )
        # CRITICAL: invalidate the ORM cache for model_id WITHOUT flushing.
        # The default ``flush=True`` would first flush the still-cached
        # ``model_id=applicant_model_id`` back to the row we just NULLed,
        # erasing our raw-SQL change. ``flush=False`` drops the cache
        # without that round-trip so subsequent reads honour the NULL in DB.
        self.tmpl_broken.invalidate_recordset(['model_id', 'model'],
                                              flush=False)

        # Stage was just created globally → auto-create already produced a
        # row for every existing job (visible=False). Reuse that row and add
        # the OK template via write() to keep the unique constraint happy.
        self.config_ok = self._get_or_create_config(
            self.job_a, self.stage, mail_template_id=self.tmpl_ok.id)
        # Create the broken config via raw SQL so we bypass our own
        # @api.constrains added in PR 2.5 — the whole point of the
        # pre-migrate is to clean rows that were created before the
        # constraint existed.
        self.env.cr.execute(
            "UPDATE hr_job_stage_config SET mail_template_id = %s "
            "WHERE id = %s",
            (self.tmpl_broken.id, self.config_ok.id),
        )
        # ``flush=False``: default ``flush=True`` would first re-write the
        # cached ``mail_template_id = tmpl_ok.id`` (from the ORM write
        # above) back onto the row we just raw-updated to ``tmpl_broken``,
        # erasing the broken-FK fixture before migrate ever sees it.
        self.config_ok.invalidate_recordset(['mail_template_id'],
                                            flush=False)

    def test_broken_fk_is_cleared(self):
        self.mod.migrate(self.env.cr, None)
        self.config_ok.invalidate_recordset(['mail_template_id'])
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

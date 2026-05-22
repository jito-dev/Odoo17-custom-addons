# -*- coding: utf-8 -*-
"""Post-migrate entry point for module version 17.0.1.0.0.

Delegates to the same ``run_backfill`` logic used by ``post_init_hook``,
so a re-upgrade (e.g. uninstall→reinstall, or version bump) replays the
backfill idempotently. Existing rows are skipped via ``search_count``.
"""
from odoo import SUPERUSER_ID, api

from odoo.addons.hr_recruitment_job_stage_config.hooks import run_backfill


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    run_backfill(env)

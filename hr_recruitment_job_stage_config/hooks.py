# -*- coding: utf-8 -*-
"""Install-time and upgrade-time hooks.

Additive-only migration: backfills the new ``hr.job.stage.config`` rows
from existing ``hr.recruitment.stage.job_ids`` M2M edges and recomputes
the new ``scope`` field. Never modifies ``hr_applicant.stage_id``.

The post-install diff captures the applicant→stage map BEFORE the
backfill, runs the backfill, then re-reads the map and logs any drift to
``ir.logging`` (R2 safety net). In normal operation drift is always 0,
because the backfill never touches the applicant table — but logging it
explicitly makes the guarantee testable from staging.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

LOG_TAG = 'hr_recruitment_job_stage_config.migration'

# Stages renamed in commit cd5a3b9 (UI/code only). If a production database
# still carries the old names, rename them in-place so the new code paths
# (which search by 'Cognitive Assessment ...') do not create duplicates.
# Pure name change — applicant.stage_id and stage.id are preserved.
IQ_TO_COGNITIVE_RENAMES = {
    'IQ Test Assigned': 'Cognitive Assessment Assigned',
    'IQ Test Completed': 'Cognitive Assessment Completed',
}


def _snapshot_applicant_stages(env):
    env.cr.execute("SELECT id, stage_id FROM hr_applicant")
    return dict(env.cr.fetchall())


def _log(env, level, message, **kwargs):
    Log = env['ir.logging'].sudo()
    Log.create({
        'name': LOG_TAG,
        'type': 'server',
        'level': level,
        'message': message,
        'path': __name__,
        'func': kwargs.get('func', '_log'),
        'line': '0',
    })
    if level == 'INFO':
        _logger.info('[%s] %s', LOG_TAG, message)
    else:
        _logger.warning('[%s] %s', LOG_TAG, message)


def _backfill_configs(env):
    """Idempotently create ``hr.job.stage.config`` rows for every
    (job, stage) pair where ``stage.job_ids`` already lists the job.
    Skip pairs that already have a config row (re-run safety).
    """
    Config = env['hr.job.stage.config'].sudo()
    Stage = env['hr.recruitment.stage'].sudo()

    created_count = 0
    skipped_count = 0
    pairs_per_job = {}

    for stage in Stage.search([]):
        if not stage.job_ids:
            continue
        for job in stage.job_ids:
            exists = Config.search_count([
                ('job_id', '=', job.id),
                ('stage_id', '=', stage.id),
            ])
            if exists:
                skipped_count += 1
                continue
            Config.create({
                'job_id': job.id,
                'stage_id': stage.id,
                'sequence': stage.sequence,
                'visible': True,
                'mail_template_id': stage.template_id.id or False,
            })
            created_count += 1
            pairs_per_job.setdefault(job.id, []).append(stage.id)

    _log(env, 'INFO',
         'Backfill complete: %d config rows created, %d skipped (already existed). '
         'Jobs touched: %s' % (
             created_count, skipped_count, sorted(pairs_per_job.keys())),
         func='_backfill_configs')
    return created_count, skipped_count


def _recompute_scope(env):
    """Force a recompute on the new stored Selection so it reflects
    ``job_ids`` for every existing stage. Safe-by-design: the compute
    is pure (read-only over job_ids); we just persist the value.
    """
    Stage = env['hr.recruitment.stage'].sudo()
    stages = Stage.search([])
    if stages:
        stages._compute_scope()
        stages.flush_recordset(['scope'])
    _log(env, 'INFO',
         'Recomputed scope on %d stages.' % len(stages),
         func='_recompute_scope')


def _rename_iq_to_cognitive(env):
    """Idempotent in-place rename of legacy IQ Test stages to match the
    Cognitive Assessment naming used by the post-cd5a3b9 codebase.
    Only the ``name`` field is mutated. Stage IDs and applicant links
    stay intact.
    """
    Stage = env['hr.recruitment.stage'].sudo()
    renamed = []
    for old_name, new_name in IQ_TO_COGNITIVE_RENAMES.items():
        legacy = Stage.search([('name', '=', old_name)])
        if not legacy:
            continue
        # If a stage with the new name already exists, leave the legacy
        # one alone — the operator may want to merge manually.
        already_renamed = Stage.search_count([('name', '=', new_name)])
        if already_renamed:
            _log(env, 'INFO',
                 "Skipped rename '%s' → '%s': target name already in use." % (
                     old_name, new_name),
                 func='_rename_iq_to_cognitive')
            continue
        legacy.write({'name': new_name})
        renamed.extend(legacy.ids)
    if renamed:
        _log(env, 'INFO',
             "Renamed %d legacy stages to Cognitive Assessment naming "
             "(stage IDs: %s)." % (len(renamed), renamed),
             func='_rename_iq_to_cognitive')


def _verify_no_applicant_drift(env, before):
    after = _snapshot_applicant_stages(env)
    drift = []
    for app_id, before_stage in before.items():
        after_stage = after.get(app_id)
        if after_stage != before_stage:
            drift.append((app_id, before_stage, after_stage))
    if drift:
        _log(env, 'WARNING',
             'R2 GUARANTEE BROKEN — applicant.stage_id changed for %d '
             'applicants during install: %s' % (
                 len(drift), drift[:50]),
             func='_verify_no_applicant_drift')
    else:
        _log(env, 'INFO',
             'R2 verification OK — applicant.stage_id unchanged for %d '
             'applicants.' % len(before),
             func='_verify_no_applicant_drift')


def run_backfill(env):
    """End-to-end backfill, callable from post_init_hook and from
    versioned post-migrate scripts. Idempotent.
    """
    before = _snapshot_applicant_stages(env)
    _rename_iq_to_cognitive(env)
    _backfill_configs(env)
    _recompute_scope(env)
    _verify_no_applicant_drift(env, before)


def post_init_hook(env):
    # Odoo 17: post_init_hook receives an Environment, not a cursor+registry.
    # Wrap in try/except so a non-fatal logging issue cannot block install.
    try:
        run_backfill(env)
    except Exception as exc:
        _logger.exception(
            "[%s] post_init_hook failed: %s — install proceeding, "
            "but config rows may not be backfilled. Run "
            "module upgrade to retry.", LOG_TAG, exc)

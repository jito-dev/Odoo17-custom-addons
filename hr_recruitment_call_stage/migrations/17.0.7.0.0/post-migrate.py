# -*- coding: utf-8 -*-
"""v17.0.7.0.0 — Etap 8 post-migrate.

Re-stamp every existing ``hr.job.stage.config`` row with
``is_call_stage=True`` whose ``call_booked_stage_id`` is either
empty or still pointing at the legacy global
``hr_recruitment_call_stage.stage_call_booked``. For each such row
the new ``_sync_call_booked_membership`` creates a per-stage paired
Call Booked stage scoped to the job.

Per consilium with the user, applicants currently sitting on the
legacy global Call Booked are left in place — this is not a prod
environment and old applicants can be wiped manually if desired.
"""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    legacy_global = env.ref(
        'hr_recruitment_call_stage.stage_call_booked',
        raise_if_not_found=False)
    domain = [('is_call_stage', '=', True)]
    if legacy_global:
        domain.append('|')
        domain.append(('call_booked_stage_id', '=', False))
        domain.append(('call_booked_stage_id', '=', legacy_global.id))
    else:
        domain.append(('call_booked_stage_id', '=', False))
    configs = env['hr.job.stage.config'].sudo().search(domain)
    if not configs:
        return
    # Clear the legacy pointer so _sync_call_booked_membership treats
    # each row as "not yet paired" and mints a fresh dedicated stage.
    configs.filtered(
        lambda c: legacy_global and c.call_booked_stage_id == legacy_global
    ).write({'call_booked_stage_id': False})
    configs._sync_call_booked_membership()

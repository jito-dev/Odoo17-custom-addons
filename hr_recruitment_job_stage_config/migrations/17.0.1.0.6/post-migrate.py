# -*- coding: utf-8 -*-
"""Post-migrate for 17.0.1.0.6.

Drops the static ``default='global'`` from ``hr.recruitment.stage.scope``
(see field definition for the full story). On existing databases this
default has already populated the column; nothing in the column itself
needs migrating, but stages that were created via the kanban "+ Stage"
flow on prior versions may have lost their ``job_ids`` because the
post-INSERT ``_inverse_scope`` cleared the M2M.

We cannot reliably recover those job_ids — the link was deleted — but
we CAN re-sync the ``scope`` value of every existing stage from its
current ``job_ids`` so the form widget reflects reality. That is the
idempotent ``_recompute_scope`` we already ship in ``hooks.py``.

Additive only: no row deletion, no applicant mutation.
"""
from odoo import api, SUPERUSER_ID

from odoo.addons.hr_recruitment_job_stage_config.hooks import _recompute_scope


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    _recompute_scope(env)

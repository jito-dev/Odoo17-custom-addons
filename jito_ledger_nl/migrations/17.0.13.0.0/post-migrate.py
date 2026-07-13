# -*- coding: utf-8 -*-

"""Post-migration for 17.0.13.0.0 — Analytic Mirror & Extend.

This version adds `base_code` + `scope` (computed-stored) to
`jito.ledger.analytic.account` and `scope` to `jito.ledger.analytic.plan`.
New writes populate them via the compute, but pre-existing rows need a
one-time recompute so every existing analytic account gets
`scope='mgt'` + `base_code=code` and every plan gets `scope='mgt'`
immediately (they carry no statutory pointer yet).

Idempotent — recomputing already-correct values is a no-op.
"""

import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    accounts = env['jito.ledger.analytic.account'].with_context(
        active_test=False,
    ).search([])
    if accounts:
        accounts._compute_base_code()
        accounts._compute_scope()
        accounts.flush_recordset(['base_code', 'scope'])
        _logger.info(
            "jito_ledger_nl 17.0.13.0.0: backfilled base_code/scope on %d "
            "analytic account(s).", len(accounts),
        )

    plans = env['jito.ledger.analytic.plan'].with_context(
        active_test=False,
    ).search([])
    if plans:
        plans._compute_scope()
        plans.flush_recordset(['scope'])
        _logger.info(
            "jito_ledger_nl 17.0.13.0.0: backfilled scope on %d analytic "
            "plan(s).", len(plans),
        )

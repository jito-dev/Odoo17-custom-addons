# -*- coding: utf-8 -*-

"""Post-migrate to 17.0.1.1.4 — backfill the management-layer chart of
accounts.

The 17.0.1.1.3 migration seeded the per-company Leading Ledger label
record but forgot to also seed the four FAAP/MGT/CLR/GRP root accounts
into `jito.ledger.account`. (The post-init hook does both, but post-init
runs only on first install — not on upgrade.)

This migration calls **both** helpers per company. Both are idempotent,
so re-runs are safe; tenants who upgraded through 17.0.1.1.3 get the
missing CoA seed here.

Migration scripts in Odoo 17 use ``migrate(cr, version)``.
"""

from odoo import api, SUPERUSER_ID

from odoo.addons.jito_ledger_core.hooks import (
    _ensure_leading_ledger_for_company,
    _ensure_roots_for_company,
)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    for company in env['res.company'].search([]):
        _ensure_leading_ledger_for_company(env, company)
        _ensure_roots_for_company(env, company)

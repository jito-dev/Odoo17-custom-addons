# -*- coding: utf-8 -*-

"""Post-migrate to 17.0.1.1.3 — backfill the per-company Leading Ledger
config record.

Earlier 17.0.1.x versions did not auto-create a `jito.ledger(kind=leading)`
record on install, which made it impossible to create an Extension
Ledger on top of the company's stock Odoo accounting (the Extension
form's base-ledger dropdown was empty).

This migration creates the Leading Ledger label record for every
existing company that doesn't already have one, calling the same helper
the post-init hook uses. Idempotent.

Migration scripts in Odoo 17 use ``migrate(cr, version)``.
"""

from odoo import api, SUPERUSER_ID

from odoo.addons.jito_ledger_core.hooks import _ensure_leading_ledger_for_company


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    for company in env['res.company'].search([]):
        _ensure_leading_ledger_for_company(env, company)

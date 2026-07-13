# -*- coding: utf-8 -*-

"""Post-migrate to 17.0.1.4.0 — backfill the per-company Non-Leading
and Extension ledger singletons.

Up to 17.0.1.3.x only the Leading Ledger was auto-seeded. From
17.0.1.4.0 the system manages **all three** as singletons:
  * Leading Ledger (label for stock Odoo accounting; pre-existing seed)
  * Non-Leading Ledger (new auto-seed)
  * Extension Ledger (new auto-seed; base hard-locked to Leading)

This migration calls the same idempotent ensure helpers the post-init
hook uses, so tenants upgrading from 17.0.1.3.x get the missing
singletons created without disturbing any manually-created ledgers.

Migration scripts in Odoo 17 use ``migrate(cr, version)``.
"""

from odoo import api, SUPERUSER_ID

from odoo.addons.jito_ledger_core.hooks import (
    _ensure_leading_ledger_for_company,
    _ensure_non_leading_ledger_for_company,
)


def migrate(cr, version):
    # NOTE (17.0.5.0.1): the Extension Ledger kind was removed. This
    # historical migration no longer seeds an extension singleton; it
    # only backfills the Leading / Non-Leading singletons.
    env = api.Environment(cr, SUPERUSER_ID, {})
    for company in env['res.company'].search([]):
        _ensure_leading_ledger_for_company(env, company)
        _ensure_non_leading_ledger_for_company(env, company)

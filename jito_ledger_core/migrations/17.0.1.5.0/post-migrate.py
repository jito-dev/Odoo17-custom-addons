# -*- coding: utf-8 -*-

"""Post-migrate to 17.0.1.5.0 — backfill the four NL invoicing-default
MGT accounts.

17.0.1.5.0 expands SEEDED_ROOTS to include MGT.RECEIVABLE,
MGT.PAYABLE, MGT.SALES, MGT.EXPENSE — the default account buckets
NL Customer Invoices / Credit Notes / Vendor Bills / Vendor Refunds
post to. ``_ensure_roots_for_company`` is idempotent — it iterates
SEEDED_ROOTS and only creates entries that don't already exist.

Migration scripts in Odoo 17 use ``migrate(cr, version)``.
"""

from odoo import api, SUPERUSER_ID

from odoo.addons.jito_ledger_core.hooks import _ensure_roots_for_company


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    for company in env['res.company'].search([]):
        _ensure_roots_for_company(env, company)

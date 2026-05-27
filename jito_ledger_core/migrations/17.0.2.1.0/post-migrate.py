# -*- coding: utf-8 -*-

"""Post-migration for 17.0.2.1.0.

Two additive backfills for existing installs:

  1. **Seed the `CADJ` (Management Adjustments) ML journal** for
     every company that doesn't already have one. Closes the gap
     where ``company.jito_default_adjustments_journal_id`` had nothing
     to point at and the Bridge / Restate / Regroup wizards fell back
     to "first journal in NL" non-deterministically.

  2. **Back-fill `company.jito_default_*_journal_id`** for the
     existing seeded CINV / CBILL journals (and the new CADJ). Until
     17.0.2.1.0 the seed only *created* the journal; the company-side
     default-journal fields stayed blank, relying on the
     invoice/bill form's code-lookup fallback. From 17.0.2.1.0 the
     fields are also written — but only when currently blank, so any
     admin override survives.

Idempotent — re-running this migration is a no-op once the seeds and
defaults are in place.
"""

import logging

from odoo import api, SUPERUSER_ID

from odoo.addons.jito_ledger_core.hooks import (
    _ensure_customer_invoices_journal_for_company,
    _ensure_vendor_bills_journal_for_company,
    _ensure_adjustments_journal_for_company,
)

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    companies = env['res.company'].search([])
    for company in companies:
        _ensure_customer_invoices_journal_for_company(env, company)
        _ensure_vendor_bills_journal_for_company(env, company)
        _ensure_adjustments_journal_for_company(env, company)
    _logger.info(
        "jito_ledger_core 17.0.2.1.0: ran seed + default-backfill across "
        "%d company(ies).",
        len(companies),
    )

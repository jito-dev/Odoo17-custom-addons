# -*- coding: utf-8 -*-

"""Post-migrate to 17.0.1.6.0:

  (1) Rename two seeded MGT accounts' display names for clarity in the
      Customer Invoice UX:
        MGT.SALES        → 'Product Sales'
        MGT.RECEIVABLE   → 'Account Receivable'
      Only renames records that still match the old seeded display
      name; tenant-edited names are preserved untouched.

  (2) Auto-seed the Customer Invoices account.journal per company,
      linked to the NL ledger via jito.ledger.journal.rel with
      default_account_id = MGT.SALES.

Migration scripts in Odoo 17 use ``migrate(cr, version)``.
"""

import logging

from odoo import api, SUPERUSER_ID

from odoo.addons.jito_ledger_core.hooks import (
    _ensure_customer_invoices_journal_for_company,
)

_logger = logging.getLogger(__name__)


# Tuples of (code, old_seed_name, new_seed_name).
RENAMES = (
    ('MGT.SALES',      'MGT — Management Sales / Revenue (NL invoicing default)', 'Product Sales'),
    ('MGT.RECEIVABLE', 'MGT — Management Receivables (NL invoicing default)',     'Account Receivable'),
)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    # (1) Targeted display-name renames
    Account = env['jito.ledger.account']
    for code, old_name, new_name in RENAMES:
        accs = Account.search([('code', '=', code), ('name', '=', old_name)])
        if accs:
            accs.write({'name': new_name})
            _logger.info(
                "jito_ledger_core 17.0.1.6.0: renamed %d %s account(s) "
                "to '%s'.",
                len(accs), code, new_name,
            )

    # (2) Customer Invoices journal backfill
    for company in env['res.company'].search([]):
        _ensure_customer_invoices_journal_for_company(env, company)

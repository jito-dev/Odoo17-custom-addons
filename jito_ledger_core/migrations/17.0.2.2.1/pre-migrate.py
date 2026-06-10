# -*- coding: utf-8 -*-

"""Pre-migration for 17.0.2.2.1.

17.0.2.2.0 introduced ``jito.ledger.journal.bank_account_id`` as a
Many2one to stock ``res.partner.bank``. The user feedback was that
both Bank Account and Suspense Account should resolve against the
**management chart of accounts** (``jito.ledger.account``), so this
release re-points the comodel.

Existing values (if any) point at ``res.partner.bank`` IDs and can't
be safely auto-mapped to ML accounts. NULL them out before Odoo's
schema sync re-creates the FK against the new target table —
otherwise the FK ADD would fail validation on stale IDs.

Idempotent — repeated runs just set already-NULL columns to NULL.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("""
        UPDATE jito_ledger_journal
           SET bank_account_id = NULL
         WHERE bank_account_id IS NOT NULL
    """)
    if cr.rowcount:
        _logger.warning(
            "jito_ledger_core 17.0.2.2.1: cleared bank_account_id on %d "
            "journal row(s) — 17.0.2.2.0 pointed it at res.partner.bank; "
            "17.0.2.2.1 retargets to jito.ledger.account. Re-pick the "
            "right ML asset account on each Bank/Cash journal.",
            cr.rowcount,
        )

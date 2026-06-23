# -*- coding: utf-8 -*-

"""Post-migration for 17.0.2.3.0.

Adds the `reconcile` Boolean to `jito.ledger.account` (HLD Decision
#11 — v1.x reconciliation). Backfills existing rows so AR/PAY and the
CLR.* clearing family are enabled for reconciliation out of the box,
matching the auto-default applied to new rows by `_compute_reconcile`.

The compute is stored with `readonly=False`, so this UPDATE establishes
the baseline once; subsequent admin toggles survive. Idempotent — re-
running is a no-op (a value already True stays True; the WHERE clause
filters by account_type / semantic_family, both immutable on a given
row).
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("""
        UPDATE jito_ledger_account
           SET reconcile = TRUE
         WHERE reconcile IS DISTINCT FROM TRUE
           AND (
                account_type IN ('asset_receivable', 'liability_payable')
                OR semantic_family = 'clr'
           )
    """)
    _logger.info(
        "jito_ledger_core 17.0.2.3.0: enabled reconcile=True on %d "
        "jito.ledger.account row(s) (AR/PAY + CLR family).",
        cr.rowcount,
    )

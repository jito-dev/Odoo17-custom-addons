# -*- coding: utf-8 -*-

"""Post-migration for 17.0.7.0.0.

Activates v1.x reconciliation (HLD Decision #11). The
`amount_residual_currency` and `reconciled` columns have lived in the
schema since 17.0.1.0.0 (reserved); this version's @compute starts
populating them from `jito.ledger.partial.reconcile` records.

Two things this migration does:

  1. **Initialize residuals.** For every existing line, set
     amount_residual_currency = amount_currency and reconciled = FALSE
     so the stored compute has a sane baseline before the first
     write touches it. (Without this, lines that haven't been
     modified since 17.0.1.0.x would carry NULL residuals until a
     write triggers _compute_residual.)

  2. **No partials exist yet** (the model itself is new in 17.0.7.0.0),
     so no other backfill is needed.

Idempotent — re-running is a no-op (the WHERE clause skips rows
that already have a non-NULL residual matching their amount_currency).
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("""
        UPDATE jito_ledger_move_line
           SET amount_residual_currency = amount_currency,
               reconciled = FALSE
         WHERE amount_residual_currency IS NULL
            OR (amount_residual_currency = 0 AND amount_currency <> 0)
    """)
    _logger.info(
        "jito_ledger_nl 17.0.7.0.0: initialized amount_residual_currency "
        "on %d jito.ledger.move.line row(s) (reconciliation v1.x active).",
        cr.rowcount,
    )

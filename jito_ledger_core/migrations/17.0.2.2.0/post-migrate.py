# -*- coding: utf-8 -*-

"""Post-migration for 17.0.2.2.0.

17.0.2.2.0 adds a required ``type`` Selection on
``jito.ledger.journal`` (mirrors stock ``account.journal.type`` —
sale / purchase / cash / bank / general). Odoo's schema sync will
have populated the new column with the field's default (`'general'`)
for every existing row. This migration corrects the two auto-seeded
rows that should carry a more specific type:

  * code ``'CINV'``  → ``type='sale'``
  * code ``'CBILL'`` → ``type='purchase'``

CADJ rows (also seeded by 17.0.2.1.0) already match the
``'general'`` default, so they don't need touching.

User-created journals stay at whatever they have (``'general'`` by
default). Admins can re-pick a type per row at any time via
**Management Ledger → Configuration → Journals**.

Idempotent — a row that's already on the correct type is a no-op.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute(
        "UPDATE jito_ledger_journal "
        "   SET type = 'sale' "
        " WHERE code = 'CINV' AND type IS DISTINCT FROM 'sale'"
    )
    sale_count = cr.rowcount
    cr.execute(
        "UPDATE jito_ledger_journal "
        "   SET type = 'purchase' "
        " WHERE code = 'CBILL' AND type IS DISTINCT FROM 'purchase'"
    )
    purchase_count = cr.rowcount
    _logger.info(
        "jito_ledger_core 17.0.2.2.0: set type='sale' on %d CINV row(s), "
        "type='purchase' on %d CBILL row(s).",
        sale_count, purchase_count,
    )

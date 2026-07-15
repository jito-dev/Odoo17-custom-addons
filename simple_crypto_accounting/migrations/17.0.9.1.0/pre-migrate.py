# -*- coding: utf-8 -*-

"""Pre-migrate to 17.0.9.1.0 — remove the legacy ``sca.journal.map``.

The v1.3.x stock-LL "Journal Mapping (legacy)" model, menu, views and
ACLs are deleted (crypto injection has posted to the Management Ledger
via ``sca.mgt.ledger.map`` since v2.0.0; the legacy map has been unused).

Odoo's module-update orphan cleanup unlinks the removed XML records and
drops the removed model's table on its own; this pre-migrate drops the
table defensively (idempotent) so no dead table lingers.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("DROP TABLE IF EXISTS sca_journal_map CASCADE")
    _logger.info(
        "simple_crypto_accounting 17.0.9.1.0: dropped legacy sca_journal_map."
    )

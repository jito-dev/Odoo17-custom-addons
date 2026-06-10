# -*- coding: utf-8 -*-

"""Pre-migration for 17.0.7.0.0.

`sca.mgt.ledger.map.journal_id` is re-pointed from `account.journal`
to `jito.ledger.journal`. Uses the `source_account_journal_id`
breadcrumb populated by `jito_ledger_core` 17.0.2.0.0's post-migrate.

Idempotent.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # When migrating from a version predating the management-ledger
    # rework (< 2.0.0), the table is created later by the ORM's schema
    # sync — it doesn't exist yet in this `pre` stage. Nothing to
    # re-point, so skip.
    cr.execute("SELECT to_regclass('public.sca_mgt_ledger_map')")
    if not cr.fetchone()[0]:
        _logger.info(
            "simple_crypto_accounting 17.0.7.0.0: sca_mgt_ledger_map "
            "absent; nothing to re-point, skipping."
        )
        return
    cr.execute("""
        UPDATE sca_mgt_ledger_map m
           SET journal_id = jlj.id
          FROM jito_ledger_journal jlj
         WHERE m.journal_id = jlj.source_account_journal_id
           AND jlj.source_account_journal_id IS NOT NULL
    """)
    _logger.info(
        "simple_crypto_accounting 17.0.7.0.0: re-pointed "
        "sca_mgt_ledger_map.journal_id on %d rows.",
        cr.rowcount,
    )

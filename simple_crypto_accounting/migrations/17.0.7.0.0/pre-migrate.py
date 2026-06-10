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

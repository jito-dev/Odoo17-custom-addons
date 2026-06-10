# -*- coding: utf-8 -*-

"""Pre-migration for 17.0.6.0.0.

Same shape as `jito_ledger_nl/migrations/17.0.6.0.0/pre-migrate.py`:
re-point `journal_id` on the three adjustment wizards from the old
`account.journal` IDs to the new `jito.ledger.journal` IDs, using the
`source_account_journal_id` breadcrumb populated by `jito_ledger_core`
17.0.2.0.0's post-migrate.

Idempotent.
"""

import logging

_logger = logging.getLogger(__name__)

_TABLES = [
    'jito_mgt_bridging',
    'jito_mgt_restatement',
    'jito_mgt_regrouping',
]


def migrate(cr, version):
    for table in _TABLES:
        cr.execute("""
            UPDATE {table} t
               SET journal_id = jlj.id
              FROM jito_ledger_journal jlj
             WHERE t.journal_id = jlj.source_account_journal_id
               AND jlj.source_account_journal_id IS NOT NULL
        """.format(table=table))
        _logger.info(
            "jito_ledger_adjustments 17.0.6.0.0: re-pointed %s.journal_id on %d rows.",
            table, cr.rowcount,
        )

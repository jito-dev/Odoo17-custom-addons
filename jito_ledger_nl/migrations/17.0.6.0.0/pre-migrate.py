# -*- coding: utf-8 -*-

"""Pre-migration for 17.0.6.0.0.

The `journal_id` FK on the following tables has been re-pointed from
`account.journal` to the new `jito.ledger.journal` model (Option C —
parallel ML journal, jito_ledger_core 17.0.2.0.0 introduces it). Odoo's
schema sync would otherwise leave the column typed for the old comodel.

We rewrite the values **before** the schema sync runs, joining on the
`source_account_journal_id` breadcrumb that `jito_ledger_core`'s
post-migrate populated when it promoted each rel row.

Tables touched here:
  * `jito_ledger_move.journal_id`
  * `res_company.jito_default_invoice_journal_id`
  * `res_company.jito_default_bill_journal_id`
  * `res_company.jito_default_adjustments_journal_id`

Idempotent. If `jito_ledger_journal` is empty (fresh install, no
legacy data), every UPDATE is a no-op.
"""

import logging

_logger = logging.getLogger(__name__)

_TARGETS = [
    ('jito_ledger_move', 'journal_id'),
    ('res_company',      'jito_default_invoice_journal_id'),
    ('res_company',      'jito_default_bill_journal_id'),
    ('res_company',      'jito_default_adjustments_journal_id'),
]


def migrate(cr, version):
    for table, column in _TARGETS:
        cr.execute("""
            UPDATE {table} t
               SET {column} = jlj.id
              FROM jito_ledger_journal jlj
             WHERE t.{column} = jlj.source_account_journal_id
               AND jlj.source_account_journal_id IS NOT NULL
        """.format(table=table, column=column))
        _logger.info(
            "jito_ledger_nl 17.0.6.0.0: re-pointed %s.%s on %d rows.",
            table, column, cr.rowcount,
        )

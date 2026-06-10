# -*- coding: utf-8 -*-

"""Pre-migration for 17.0.6.0.1.

Follow-up fix for 17.0.6.0.0's Option-C refactor.

The 17.0.6.0.0 pre-migrate re-pointed ``jito_ledger_move.journal_id``
from old ``account.journal`` IDs to new ``jito.ledger.journal`` IDs,
but I missed ``jito_ledger_move_line.journal_id`` — a **stored
related** field on the move's journal_id. Its column values stayed
frozen at the old account.journal IDs while the model's comodel
switched, so any line whose stored value happened to coincide with a
real jito.ledger.journal row "worked", and the rest threw
"Missing Record (jito.ledger.journal(X,))" the moment they were
displayed.

This migration copies the now-correct ``jito_ledger_move.journal_id``
into ``jito_ledger_move_line.journal_id`` row-by-row, which is the
correct recompute for a related field. Idempotent.

It also logs (but does not auto-touch) any line whose `journal_id`
ends up pointing at a non-existent jito.ledger.journal row — those
are the rare orphan moves whose parent's journal_id translation
itself failed in 17.0.6.0.0 (e.g. the original `account.journal` had
no `jito.ledger.journal.rel` row). They need manual cleanup.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # Step 1 — copy the parent move's (now-correct) journal_id into
    # every line. Stored related field, so this is the "official"
    # post-migration recompute.
    cr.execute("""
        UPDATE jito_ledger_move_line ml
           SET journal_id = m.journal_id
          FROM jito_ledger_move m
         WHERE ml.move_id = m.id
           AND ml.journal_id IS DISTINCT FROM m.journal_id
    """)
    _logger.info(
        "jito_ledger_nl 17.0.6.0.1: synced jito_ledger_move_line."
        "journal_id from parent move on %d rows.",
        cr.rowcount,
    )

    # Step 2 — surface any orphans: move.journal_id values that don't
    # exist in jito_ledger_journal. These are the rows the 17.0.6.0.0
    # pre-migrate couldn't translate (no source_account_journal_id
    # match). Log them so the user can manually reassign or unlink.
    cr.execute("""
        SELECT m.id, m.name, m.journal_id
          FROM jito_ledger_move m
     LEFT JOIN jito_ledger_journal j ON j.id = m.journal_id
         WHERE m.journal_id IS NOT NULL
           AND j.id IS NULL
    """)
    orphans = cr.fetchall()
    if orphans:
        _logger.warning(
            "jito_ledger_nl 17.0.6.0.1: %d jito.ledger.move row(s) "
            "reference a non-existent jito.ledger.journal — these "
            "weren't translated by the 17.0.6.0.0 migration (no "
            "matching jito.ledger.journal.rel row at the time). "
            "Sample: %s. Manual fix: edit the move and re-pick a "
            "valid journal, or unlink the move if it was a draft "
            "test entry.",
            len(orphans),
            orphans[:5],
        )

# -*- coding: utf-8 -*-

"""Pre-migration for 17.0.8.0.0.

The mapping's asset / counterpart / currency are no longer
standalone editable fields — they're sourced from the journal's
Bank/Cash Configuration and the watched token's currency.

Before Odoo's schema sync drops the now-unstored columns on
``sca_mgt_ledger_map``, copy the values up to the single sources of
truth so existing installs don't lose their config:

  * ``jito_ledger_journal.bank_account_id``      ← mapping.asset_account_id
  * ``jito_ledger_journal.suspense_account_id``  ← mapping.counterpart_account_id
  * ``sca_token.currency_id``                    ← mapping.currency_id

Only fills targets that are currently NULL — never overwrites a
value an admin already set on the journal or the token.

Idempotent.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # When migrating from a version predating the management-ledger
    # rework (< 2.0.0), the table is created later by the ORM's schema
    # sync — it doesn't exist yet in this `pre` stage. There are no
    # mapping rows to lift values from, so skip.
    cr.execute("SELECT to_regclass('public.sca_mgt_ledger_map')")
    if not cr.fetchone()[0]:
        _logger.info(
            "simple_crypto_accounting 17.0.8.0.0: sca_mgt_ledger_map "
            "absent; nothing to lift, skipping."
        )
        return

    # 1. Lift asset accounts to the journal's bank_account_id.
    cr.execute("""
        UPDATE jito_ledger_journal j
           SET bank_account_id = m.asset_account_id
          FROM sca_mgt_ledger_map m
         WHERE j.id = m.journal_id
           AND j.bank_account_id IS NULL
           AND m.asset_account_id IS NOT NULL
    """)
    _logger.info(
        "simple_crypto_accounting 17.0.8.0.0: lifted asset_account "
        "into jito_ledger_journal.bank_account_id on %d journal(s).",
        cr.rowcount,
    )

    # 2. Lift counterpart accounts to the journal's suspense_account_id.
    cr.execute("""
        UPDATE jito_ledger_journal j
           SET suspense_account_id = m.counterpart_account_id
          FROM sca_mgt_ledger_map m
         WHERE j.id = m.journal_id
           AND j.suspense_account_id IS NULL
           AND m.counterpart_account_id IS NOT NULL
    """)
    _logger.info(
        "simple_crypto_accounting 17.0.8.0.0: lifted counterpart_account "
        "into jito_ledger_journal.suspense_account_id on %d journal(s).",
        cr.rowcount,
    )

    # 3. Lift mapping.currency_id to the watched token's currency_id.
    cr.execute("""
        UPDATE sca_token t
           SET currency_id = m.currency_id
          FROM sca_mgt_ledger_map m
         WHERE t.id = m.token_id
           AND t.currency_id IS NULL
           AND m.currency_id IS NOT NULL
    """)
    _logger.info(
        "simple_crypto_accounting 17.0.8.0.0: lifted mapping currency "
        "into sca_token.currency_id on %d watched token(s).",
        cr.rowcount,
    )

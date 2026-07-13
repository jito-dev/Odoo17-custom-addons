# -*- coding: utf-8 -*-

"""Pre-migrate to 17.0.6.0.0 — remove the account-category feature.

17.0.6.0.0 deletes the ``jito.ledger.account.category`` model (and its
"add to category" wizard) and the whole "Categorized" reporting feature
that was built on it. Grouping is now driven by account codes /
``account_type`` alone.

Odoo's module-update orphan cleanup drops the removed models' tables and
unlinks the removed XML records (menus, actions, report + ACLs) on its
own. What it does NOT do is drop the orphaned ``category_id`` column left
on ``jito_ledger_account`` (removing a code-defined field keeps the DB
column). This pre-migrate drops it explicitly so no dead column lingers,
and drops the category tables defensively (idempotent — ``IF EXISTS``).
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # Drop the orphaned FK column on the account table.
    cr.execute("""
        ALTER TABLE IF EXISTS jito_ledger_account
        DROP COLUMN IF EXISTS category_id
    """)

    # Drop the category + wizard tables (Odoo's _process_end also does this
    # for removed models; IF EXISTS keeps both paths safe).
    cr.execute("DROP TABLE IF EXISTS jito_ledger_account_category CASCADE")
    cr.execute(
        "DROP TABLE IF EXISTS jito_ledger_account_category_add_wizard CASCADE"
    )

    _logger.info(
        "jito_ledger_core 17.0.6.0.0: removed account-category column/tables."
    )

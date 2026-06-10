# -*- coding: utf-8 -*-

"""Post-migrate to 17.0.1.1.0 — clean up orphan accounts seeded by the
prior post_init_hook into stock `account.account`.

Versions 17.0.1.0.0 .. 17.0.1.0.2 incorrectly seeded FAAP.ROOT,
MGT.ROOT, CLR.ROOT, GRP.ROOT into Odoo's `account.account` and added a
@constrains extension to that model. Per HLD Decision #13, the
management-layer chart now lives in `jito.ledger.account` and stock
`account.account` is left strictly untouched.

This migration removes those four orphan accounts from `account.account`,
**but only if they have no journal items** (i.e., no posted activity).
If any of them have been used, we leave them in place and log a warning
— operators can clean them up manually after verifying.

Idempotent: a re-run finds nothing to clean up. Safe on systems that
never installed the buggy version (they simply have no orphans).

Migration scripts in Odoo 17 use the legacy ``migrate(cr, version)``
signature (unlike ``post_init_hook`` which uses ``(env)``); we
construct an env from the cursor.
"""

import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

ORPHAN_CODES = ('FAAP.ROOT', 'MGT.ROOT', 'CLR.ROOT', 'GRP.ROOT')


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    Account = env['account.account']
    AccountMoveLine = env['account.move.line']

    orphans = Account.search([('code', 'in', list(ORPHAN_CODES))])
    if not orphans:
        return

    to_delete = Account
    skipped = []
    for acc in orphans:
        used = AccountMoveLine.search_count([('account_id', '=', acc.id)])
        if used:
            skipped.append((acc.code, acc.company_id.display_name, used))
        else:
            to_delete |= acc

    if to_delete:
        codes = sorted(set(to_delete.mapped('code')))
        to_delete.unlink()
        _logger.info(
            "jito_ledger_core 17.0.1.1.0: removed %d orphan account.account "
            "record(s) from prior installs (codes: %s).",
            len(to_delete), ', '.join(codes),
        )

    for code, company, used in skipped:
        _logger.warning(
            "jito_ledger_core 17.0.1.1.0: account.account code=%s in company "
            "'%s' has %d journal item(s) and was NOT removed. Review and "
            "delete manually if appropriate.",
            code, company, used,
        )

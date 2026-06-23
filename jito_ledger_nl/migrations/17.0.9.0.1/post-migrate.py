# -*- coding: utf-8 -*-

"""Post-migration for 17.0.9.0.1.

Enables Analytic Accounting by default on existing installs. The
fresh-install case is handled by the noupdate="1" record in
``security/groups.xml`` (base.group_user implies group_mgmt_ledger_analytic);
that record is skipped on *update*, so existing databases need this
one-time grant.

Adds ``group_mgmt_ledger_analytic`` to ``base.group_user.implied_ids``
and propagates it to every current internal user, so the
"Analytic Accounting" toggle in Management Ledger Settings reads as ON
after the upgrade. Runs once (this version only) — a later un-check by
the user is therefore preserved across future upgrades.

Idempotent: re-adding an already-present implied group / user is a no-op.
"""

import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    group = env.ref(
        'jito_ledger_nl.group_mgmt_ledger_analytic',
        raise_if_not_found=False,
    )
    base_user = env.ref('base.group_user', raise_if_not_found=False)
    if not group or not base_user:
        _logger.warning(
            "jito_ledger_nl 17.0.9.0.0: analytic group or base.group_user "
            "missing; skipping default-on grant."
        )
        return
    base_user.write({'implied_ids': [(4, group.id)]})
    # Grant retroactively to existing internal users (write on implied_ids
    # alone does not always back-fill current members).
    group.sudo().write({'users': [(4, user.id) for user in base_user.users]})
    _logger.info(
        "jito_ledger_nl 17.0.9.0.1: Analytic Accounting enabled by default "
        "(granted to %d internal user(s)).",
        len(base_user.users),
    )

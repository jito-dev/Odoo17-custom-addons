# -*- coding: utf-8 -*-
import logging

_logger = logging.getLogger(__name__)

EXPENSE_TYPES = ('expense', 'expense_direct_cost')


def post_init_hook(env):
    """Categorise the existing chart of accounts on install/upgrade.

    Only fills blanks, so re-running an upgrade never undoes a manual override.
    The stored related field on account.move.line is recomputed by the ORM when
    the account changes, so no manual backfill is needed here.
    """
    accounts = env['account.account'].search([
        ('account_type', 'in', EXPENSE_TYPES),
        ('expense_category_id', '=', False),
    ])
    accounts._jito_assign_expense_categories()

    remaining = accounts.filtered(lambda a: not a.expense_category_id)
    _logger.info(
        "jito_expense_dashboard: categorised %s expense accounts, %s left blank",
        len(accounts) - len(remaining), len(remaining),
    )

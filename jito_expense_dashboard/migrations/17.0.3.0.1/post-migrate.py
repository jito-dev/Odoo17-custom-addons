# -*- coding: utf-8 -*-
"""Backfill expense categories on upgrade.

``post_init_hook`` only runs on a fresh install (odoo/modules/loading.py checks
``new_install``), so an existing installation needs this migration to get its
chart of accounts categorised. Writing the category on the accounts also makes
the ORM recompute the stored related field on account.move.line.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

EXPENSE_TYPES = ('expense', 'expense_direct_cost')


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    accounts = env['account.account'].with_context(active_test=False).search([
        ('account_type', 'in', EXPENSE_TYPES),
        ('expense_category_id', '=', False),
    ])
    accounts._jito_assign_expense_categories()
    env.flush_all()

    remaining = accounts.filtered(lambda a: not a.expense_category_id)
    _logger.info(
        "jito_expense_dashboard: categorised %s expense accounts, %s left blank",
        len(accounts) - len(remaining), len(remaining),
    )

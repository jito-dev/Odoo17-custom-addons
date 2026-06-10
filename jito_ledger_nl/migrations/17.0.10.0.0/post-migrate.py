# -*- coding: utf-8 -*-
"""Backfill ``balance`` / ``debit`` / ``credit`` on existing
``jito.ledger.move.line`` records.

17.0.10.0.0 — ADR reverses HLD Decision #8: company-currency
amounts are now stored (frozen at posting) instead of translated at
report time. Existing rows had only ``amount_currency``; this script
populates the new columns by translating each line's
``amount_currency`` to company currency at ``line.date`` via
``res.currency._convert``.

Idempotent: lines that already have a non-zero balance from a prior
upgrade are skipped.
"""

from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Line = env['jito.ledger.move.line']
    # Match the standard "needs backfill" criterion: any line with a
    # non-zero amount_currency but a zero balance. Lines truly worth
    # zero in tx currency need no backfill either way.
    lines = Line.search([
        ('amount_currency', '!=', 0.0),
        ('balance', '=', 0.0),
    ])
    if not lines:
        return
    for line in lines:
        company_currency = line.company_id.currency_id
        if not company_currency or not line.currency_id:
            continue
        if line.currency_id == company_currency:
            line.balance = line.amount_currency
            continue
        line.balance = line.currency_id._convert(
            line.amount_currency, company_currency,
            line.company_id, line.date,
        )

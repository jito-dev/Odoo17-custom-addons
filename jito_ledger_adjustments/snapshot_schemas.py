# -*- coding: utf-8 -*-

"""Versioned schema registry for jito.ledger.trace.source_snapshot.

Per HLD Decision #3: forward-compatible reader. Each snapshot row
carries `snapshot_version` (Char). Writers emit the latest version;
readers tolerate unknown future versions by ignoring unrecognised keys
(the documented field set is rendered, the rest carry a "schema
upgrade pending" indicator in reports).

This module documents the shipped versions. v1 ships in 17.0.1.0.0.
Bump the version string when fields are added; readers older than the
new version see only the fields they know about.
"""

CURRENT_VERSION = '1'

# Schema version → set of expected keys. New keys are additive only;
# never remove a key in a backward-compatible bump.
SCHEMAS = {
    '1': {
        # The LL source line's identity at trace creation time.
        'move_id', 'move_name',
        'line_id', 'line_name',
        'account_id', 'account_code', 'account_name',
        # Statutory amounts (frozen at snapshot time).
        'debit', 'credit',
        'amount_currency', 'currency_id', 'currency_name',
        # Context.
        'date', 'partner_id', 'partner_name',
        'company_id', 'company_name',
    },
}


def snapshot_account_move_line(line):
    """Build the v1 snapshot dict for a stock account.move.line record.

    Idempotent and pure: relies on read-only field access. Returns a
    plain dict ready to be serialised into the JSON `source_snapshot`
    column.
    """
    return {
        'move_id': line.move_id.id if line.move_id else None,
        'move_name': line.move_id.name if line.move_id else None,
        'line_id': line.id,
        'line_name': line.name,
        'account_id': line.account_id.id if line.account_id else None,
        'account_code': line.account_id.code if line.account_id else None,
        'account_name': line.account_id.name if line.account_id else None,
        'debit': line.debit,
        'credit': line.credit,
        'amount_currency': line.amount_currency,
        'currency_id': line.currency_id.id if line.currency_id else None,
        'currency_name': line.currency_id.name if line.currency_id else None,
        'date': line.date.isoformat() if line.date else None,
        'partner_id': line.partner_id.id if line.partner_id else None,
        'partner_name': line.partner_id.display_name if line.partner_id else None,
        'company_id': line.company_id.id if line.company_id else None,
        'company_name': line.company_id.display_name if line.company_id else None,
    }

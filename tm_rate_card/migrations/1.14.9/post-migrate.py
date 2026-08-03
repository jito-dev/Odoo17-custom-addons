# -*- coding: utf-8 -*-
"""One-off backfill of `tm_adjusted_hours` values truncated by the `digits='Hours'` bug.

Background (see CHANGELOG 1.14.8): until v1.14.8 the field declared `digits='Hours'`,
which referenced a non-existent `decimal.precision` record, so the ORM rounded every
value to 2 decimals before writing it (00:20 stored as 0.33 instead of 0.3333...).
v1.14.8 stopped the bleeding for new writes but deliberately left history untouched.

This script restores the truncated rows for **July 2026 only** - the window agreed for
the first backfill pass. Later windows get their own migration directory so each pass
is reviewable and runs exactly once.

Restoration criterion: `tm_adjusted_hours` equals `unit_amount` rounded to 2 decimals
but is not equal to `unit_amount` itself. That is the signature of the truncation - the
field is initialised to `unit_amount` on create and auto-synced with it until a PM
edits it, so a value that still matches the rounded logged hours was never adjusted by
hand. Rows a PM genuinely edited differ at the 2nd decimal and are left alone.

Rows whose value is already locked into a financial document are skipped outright: an
invoiced timesheet, or one belonging to a billing run in state `invoiced`/`closed`.
Changing those would rewrite stored totals underneath a closed document. They keep
their truncated value; correcting them is a business decision, not a migration.
"""

import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

# Backfill window: July 2026. DATE_TO is exclusive.
DATE_FROM = '2026-07-01'
DATE_TO = '2026-08-01'

# Signature of a value truncated to 2 decimals by the old `digits='Hours'` declaration.
# Compared with a tolerance because both columns are float8 since v1.14.8.
TRUNCATED = """
    l.tm_adjusted_hours IS NOT NULL
    AND abs(l.tm_adjusted_hours - round(l.unit_amount::numeric, 2)::float8) < 1e-9
    AND abs(l.tm_adjusted_hours - l.unit_amount) > 1e-9
"""

LOCKED_BY_INVOICE = """
    EXISTS (SELECT 1 FROM account_move m
             WHERE m.id = l.timesheet_invoice_id
               AND m.state != 'cancel')
"""

LOCKED_BY_BILLING_RUN = """
    EXISTS (SELECT 1 FROM tm_billing_run_line_timesheet t
              JOIN tm_billing_run_line rl ON rl.id = t.billing_line_id
              JOIN tm_billing_run r ON r.id = rl.billing_run_id
             WHERE t.timesheet_id = l.id
               AND r.state IN ('invoiced', 'closed'))
"""


def _column_exists(cr, table, column):
    cr.execute(
        "SELECT 1 FROM information_schema.columns WHERE table_name = %s AND column_name = %s",
        (table, column),
    )
    return bool(cr.fetchone())


def _table_exists(cr, table):
    cr.execute("SELECT to_regclass(%s)", (table,))
    return cr.fetchone()[0] is not None


def _locked_clauses(cr):
    """Build the skip conditions that apply to this database.

    `timesheet_invoice_id` comes from `sale_timesheet` and the billing run tables from
    `tm_billing_control`; neither is a hard dependency of this module, so each guard is
    only applied when its schema is actually present.
    """
    clauses = []
    if _column_exists(cr, 'account_analytic_line', 'timesheet_invoice_id'):
        clauses.append(LOCKED_BY_INVOICE)
    else:
        _logger.info("tm_rate_card 1.14.9: no timesheet_invoice_id column, skipping invoice guard")
    if _table_exists(cr, 'tm_billing_run_line_timesheet'):
        clauses.append(LOCKED_BY_BILLING_RUN)
    else:
        _logger.info("tm_rate_card 1.14.9: tm_billing_control not installed, skipping billing run guard")
    return clauses


def migrate(cr, version):
    if not version:
        # Fresh install - there is no legacy data to repair.
        return

    locked = _locked_clauses(cr)
    locked_sql = ' OR '.join(locked) if locked else 'FALSE'
    params = (DATE_FROM, DATE_TO)

    # Report what is being left behind before touching anything - a silent skip would
    # read as "the whole window was repaired".
    cr.execute(
        """
        SELECT count(*) FROM account_analytic_line l
         WHERE l.date >= %%s AND l.date < %%s AND (%s) AND (%s)
        """ % (TRUNCATED, locked_sql),
        params,
    )
    skipped = cr.fetchone()[0]

    cr.execute(
        """
        SELECT l.id FROM account_analytic_line l
         WHERE l.date >= %%s AND l.date < %%s AND (%s) AND NOT (%s)
        """ % (TRUNCATED, locked_sql),
        params,
    )
    ids = [row[0] for row in cr.fetchall()]

    if not ids:
        _logger.info(
            "tm_rate_card 1.14.9: nothing to backfill for %s..%s (%s locked row(s) skipped)",
            DATE_FROM, DATE_TO, skipped,
        )
        return

    cr.execute(
        "UPDATE account_analytic_line SET tm_adjusted_hours = unit_amount WHERE id IN %s",
        (tuple(ids),),
    )
    _logger.info(
        "tm_rate_card 1.14.9: restored tm_adjusted_hours on %s timesheet(s) in %s..%s "
        "(%s locked row(s) skipped)",
        len(ids), DATE_FROM, DATE_TO, skipped,
    )

    # The raw UPDATE bypasses the ORM, so stored fields computed from tm_adjusted_hours
    # still hold values derived from the truncated hours. modified() walks the dependency
    # graph and marks them for recomputation - this covers tm_billable_amount (same
    # record) and tm.rate.card.entry.timesheet_hours (plain one2many traversal).
    env = api.Environment(cr, SUPERUSER_ID, {})
    env.invalidate_all()
    env['account.analytic.line'].browse(ids).modified(['tm_adjusted_hours'])
    env.flush_all()

    # NOTE: billing run aggregates are NOT repaired here - see
    # `end-recompute_billing_totals.py` in this directory for why.

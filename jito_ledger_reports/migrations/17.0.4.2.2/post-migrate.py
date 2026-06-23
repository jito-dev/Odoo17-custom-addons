# -*- coding: utf-8 -*-

"""Post-migration for 17.0.4.2.2.

Force-set the Partner Ledger column sequences so the column order matches
the handler's emission order:

    10 Journal · 20 Account · 30 Invoice Date ·
    40 Debit   · 50 Credit  · 60 Amount Currency · 70 Balance

Why a migration: when an upgrade is partial — e.g. the server was
restarted (Python reloaded) without "Upgrade" being clicked in Apps —
the data XML may not re-run, leaving the existing `account.report.column`
records at their 17.0.4.2.0 sequences while the handler is already
emitting columns in the new order. The misalignment produces visible
column/header mismatches (e.g. "Balance" header showing dates).

This migration writes the sequences directly by xmlid, which is
idempotent and independent of XML reload behavior.
"""

import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


_TARGET_SEQUENCES = (
    ('jito_ledger_reports.management_partner_ledger_report_journal', 10),
    ('jito_ledger_reports.management_partner_ledger_report_account', 20),
    ('jito_ledger_reports.management_partner_ledger_report_invoice_date', 30),
    ('jito_ledger_reports.management_partner_ledger_report_debit', 40),
    ('jito_ledger_reports.management_partner_ledger_report_credit', 50),
    ('jito_ledger_reports.management_partner_ledger_report_amount_currency', 60),
    ('jito_ledger_reports.management_partner_ledger_report_balance', 70),
)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    for xmlid, seq in _TARGET_SEQUENCES:
        column = env.ref(xmlid, raise_if_not_found=False)
        if not column:
            _logger.warning(
                "jito_ledger_reports 17.0.4.2.2: column %s missing; "
                "skipping sequence fix (will be created by the XML "
                "data load if absent).", xmlid,
            )
            continue
        if column.sequence != seq:
            column.sequence = seq
    _logger.info(
        "jito_ledger_reports 17.0.4.2.2: partner ledger column "
        "sequences aligned to handler emission order."
    )

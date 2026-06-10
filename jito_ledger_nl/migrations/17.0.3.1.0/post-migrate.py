# -*- coding: utf-8 -*-

"""Backfill jito.ledger.move.line.display_type for existing data.

17.0.3.1.0 introduces ``display_type`` to discriminate user-edited
product lines from the auto-generated AR/AP balancing line. Without
this backfill, posted invoices (whose balancing line predates the
field) would surface in the Customer Invoice form's "Invoice Lines"
tab, polluting the user's view.

Strategy:
  * Lines on invoice-style moves whose account matches the move's
    partner_balancing_account (MGT.RECEIVABLE / MGT.PAYABLE per the
    company's defaults) are flagged display_type='payment_term'.
  * All other lines on invoice-style moves are flagged 'product'.
  * Lines on plain journal entries (move_type='entry') keep
    display_type=NULL so they remain unaffected.
"""

import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Move = env['jito.ledger.move']
    invoice_moves = Move.search([
        ('move_type', 'in', ['out_invoice', 'out_refund', 'in_invoice', 'in_refund']),
    ])
    if not invoice_moves:
        _logger.info("jito_ledger_nl 17.0.3.1.0: no invoice-style moves; "
                     "nothing to backfill.")
        return
    pt_count = 0
    prod_count = 0
    for move in invoice_moves:
        partner_account = move._get_partner_balancing_account()
        for line in move.line_ids:
            if line.display_type:
                continue
            if partner_account and line.account_id == partner_account:
                line.display_type = 'payment_term'
                pt_count += 1
            else:
                line.display_type = 'product'
                prod_count += 1
    _logger.info(
        "jito_ledger_nl 17.0.3.1.0: backfilled display_type on "
        "%d payment_term + %d product line(s) across %d move(s).",
        pt_count, prod_count, len(invoice_moves),
    )

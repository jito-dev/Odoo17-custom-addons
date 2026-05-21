# -*- coding: utf-8 -*-
{
    'name': 'Management Ledger — Non-Leading',
    'version': '17.0.5.3.0',
    'category': 'Management Ledger',
    'summary': 'Parallel-entry tables (jito.ledger.move + .line) and the '
               'Non-Leading Ledger document lifecycle.',
    'description': """
Management Ledger — Non-Leading
================================

Phase 2 of the management-ledger feature (see docs/HLD.md and
docs/IMPLEMENTATION_PLAN.md §5).

Provides:
  * jito.ledger.move — the single shared parallel-entry table. Hosts NL
    documents, extension adjustments (Phase 3), and the four management-
    adjustment outputs (Phase 4). entry_type discriminates.
  * jito.ledger.move.line — line under the move. Stores transaction
    currency only (signed amount_currency); no debit/credit/balance
    company-currency columns (HLD Decision #8). Reserves
    amount_residual_currency + reconciled for v1.x reconciliation
    (HLD Decision #11).
  * Per-currency balance constraint on jito.ledger.move (HLD Decision #10).
  * Period-lock inheritance via company._get_user_fiscal_lock_date()
    (HLD Decision #12) — locking the LL fiscal year also locks NL postings
    in that range.
  * Ledger isolation: every line's ledger_id matches its move's
    ledger_id (line.ledger_id is related/stored, so this is structural).
  * GRP.* posting forbidden; CLR.* posting only from mgt_bridge entries
    (HLD §4.4).
  * State machine: draft -> posted -> reversed. action_post runs all
    constraints; action_reverse creates a counter-move (additive
    reversal) and flags the original.
  * Standalone "Journal Entries" submenu under the Management Ledger
    top-level app.

This module ships no FK from jito_ledger_* into account.move* — the
parallel-record model (FR-13) is enforced at the schema level.

Out of scope here (Phase 4 / v1.x):
  * Reconciliation matching logic (Decision #11 reserves the schema)
  * Semantic adjustment models (Phase 4)
  * NL-specific invoice/bill/payment forms (Phase 2.5 if UX warrants)
  * Reports / FX presentation translation (Phase 5)
""",
    'author': 'JITO LTD',
    'website': 'https://jito.dev',
    'license': 'LGPL-3',
    'depends': [
        'jito_ledger_core',
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/record_rules.xml',
        'data/ir_sequence.xml',
        'views/jito_ledger_move_views.xml',
        'views/jito_ledger_move_line_views.xml',
        'views/jito_ledger_invoice_views.xml',
        'views/jito_ledger_statutory_view_views.xml',
        'views/jito_ledger_statutory_entry_view_views.xml',
        'views/res_config_settings_views.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}

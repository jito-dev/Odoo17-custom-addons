# -*- coding: utf-8 -*-
{
    'name': 'Management Ledger Core',
    'version': '17.0.3.2.1',
    'category': 'Management Ledger',
    'summary': 'Foundation for the management-accounting layer: ledger config, '
               'separate management-layer chart of accounts (FAAP/MGT/CLR/GRP), '
               'security groups, and standalone UI app.',
    'description': """
Management Ledger Core
======================

Phase 1 of the management-ledger feature (see docs/HLD.md).

Provides:
  * jito.ledger configuration model (kind: leading / non_leading / extension)
  * jito.ledger.account — management-layer chart of accounts (per HLD
    Decision #13). Stock Odoo's account.account is NOT extended, NOT
    seeded, NOT constrained — it stays exactly as Odoo ships.
  * jito.ledger.journal.rel join model linking ledgers to account.journal
    (no schema change to account.journal, per HLD Decision #9)
  * Semantic-prefix @constrains on jito.ledger.account.code enforcing
    FAAP / MGT / CLR / GRP namespacing (HLD §4.4)
  * Four security groups (group_mgmt_ledger_*) extending the stock
    Odoo accounting groups
  * Multi-company record rules on the new ledger models (FR-02 LL
    immutability is enforced at schema level via the absence of any FK
    from jito_ledger_* tables into account.move*; mgmt-layer code
    physically cannot write to LL tables)
  * Standalone top-level "Management Ledger" application menu — not
    nested under stock Accounting (per HLD Decision #14)
  * post_init_hook seeding one root account per semantic family
    (FAAP.ROOT / MGT.ROOT / CLR.ROOT / GRP.ROOT) into jito.ledger.account
    for every existing company (HLD Decisions #2 + #13)

This module ships no models for journal entries themselves — the parallel-
entry tables (jito.ledger.move / .line) live in jito_ledger_nl (Phase 2).

Out of scope here (deferred to later phases or v1.x):
  * NL invoice / bill / payment lifecycle (Phase 2)
  * Extension Ledger view (Phase 3)
  * Semantic adjustments and traceability (Phase 4)
  * Reports (Phase 5)
  * Reconciliation, backfill, CEX FX connector (v1.x)
""",
    'author': 'JITO LTD',
    'website': 'https://jito.dev',
    'license': 'LGPL-3',
    'depends': [
        'account',
        'mail',
    ],
    'data': [
        'security/groups.xml',
        'security/ir.model.access.csv',
        'security/record_rules.xml',
        'wizards/jito_faap_sync_wizard_views.xml',
        'wizards/jito_ledger_account_category_add_wizard_views.xml',
        'views/jito_ledger_account_category_views.xml',
        'views/jito_ledger_views.xml',
        'views/jito_ledger_account_views.xml',
        'views/jito_ledger_journal_views.xml',
        'views/menus.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': True,
    'auto_install': False,
}

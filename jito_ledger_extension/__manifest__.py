# -*- coding: utf-8 -*-
{
    'name': 'Management Ledger — Extension',
    'version': '17.0.1.0.0',
    'category': 'Management Ledger',
    'summary': 'UX polish for Extension Ledgers: stat buttons + quick-create action.',
    'description': """
Management Ledger — Extension
=============================

Phase 3 of the management-ledger feature (see docs/HLD.md and
docs/IMPLEMENTATION_PLAN.md §6).

Per HLD Decision #4, extension entries already live in jito.ledger.move
with entry_type='ext_adjustment' (Phase 2 schema). This module adds no
new tables and no new ACLs — purely UX polish:

  * Stat button "Adjustments" on the kind=extension ledger form:
    count of ext_adjustment moves on this ledger; click to open a
    filtered tree.
  * Stat button "Base Entries" on the kind=extension ledger form:
    count from the base ledger — account.move when base.kind=leading,
    jito.ledger.move when base.kind=non_leading. Click opens the
    corresponding tree.
  * Header button "New Extension Adjustment" on the kind=extension
    ledger form: opens a new jito.ledger.move form with ledger_id and
    entry_type pre-filled.
  * All controls hidden on non-extension ledgers.

Per HLD Decision #7, v1 uses on-the-fly aggregation for combined
reporting (no materialised SQL view). This module deliberately does
not implement reporting — that's Phase 5.
""",
    'author': 'JITO LTD',
    'website': 'https://jito.dev',
    'license': 'LGPL-3',
    'depends': [
        'jito_ledger_nl',
    ],
    'data': [
        'views/jito_ledger_extension_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}

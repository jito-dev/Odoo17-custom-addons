# -*- coding: utf-8 -*-
{
    'name': 'Management Ledger — Reports',
    'version': '17.0.3.0.0',
    'category': 'Management Ledger',
    'summary': 'Management-layer reports (Trial Balance for v1) with FX '
               'presentation translation at report time.',
    'description': """
Management Ledger — Reports
============================

Phase 5 of the management-ledger feature (see docs/HLD.md and
docs/IMPLEMENTATION_PLAN.md §8).

17.0.2.0.0 promotes the Reports section to a top-level **Reporting**
menu under Management Ledger (sibling of Accounting) and adds a new
**Management Partner Ledger** alongside Trial Balance. Both reports
share `jito.ledger.report.handler.base` for domain construction,
date-range parsing, and FX translation, so figures remain consistent.

17.0.3.0.0 splits Partner Ledger into three scope-specific entries
under one report: **Management** (jito.ledger.move.line — the parallel
management entries), **FAAP Projection** (jito.ledger.statutory.view —
Leading Ledger lines surfaced via FAAP mirrors), and **Combined**
(both, partner-aggregated with source-tagged drill-down).

The original Trial Balance — the foundational report from which P&L
and Balance Sheet variants can be derived in later releases — is
unchanged in behavior:

  * Pulls posted, non-voided lines from `jito.ledger.move.line`
    (Phase 2 schema).
  * Aggregates by `jito.ledger.account` (the management chart).
  * Presents totals in **company currency**, translated from the line's
    transaction currency at report time using
    `res.currency._get_query_currency_table()` per FR-23.
  * Adds a **Rate Policy** option (`period_end` / `spot_today`) per
    HLD Decision #1 (parent FR-23). Period-end is the default.
  * Inherits the standard `account.report` infrastructure for date
    range filtering and column groups.

Pattern documented in HLD §6 — AbstractModel inheriting
`account.report.custom.handler`. Reused stock Odoo source files:
  * `odoo17_enterprise/odoo/addons/account_reports/models/account_report.py:67-83, 6074-6147`
  * `odoo17_enterprise/odoo/addons/account_reports/models/account_general_ledger.py:14-85`
  * `odoo17_enterprise/odoo/addons/account_reports/data/general_ledger.xml:3-48`

Out of scope for v1.0.0 (deferred to v1.x):
  * Management P&L (revenue / expenses categorization view).
  * Management Balance Sheet (assets / liabilities / equity hierarchy).
  * Combined LL + Management view (joining `account.move.line` with
    `jito.ledger.move.line` in one report).
  * On-chain oracle / CEX FX feed (HLD Decision #1) — uses
    `res.currency.rate` populated by `jito_ecb_exchange_rate` in v1.
""",
    'author': 'JITO LTD',
    'website': 'https://jito.dev',
    'license': 'LGPL-3',
    'depends': [
        'jito_ledger_extension',
        'jito_ledger_adjustments',
        'account_reports',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/account_report.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}

# -*- coding: utf-8 -*-
{
    'name': 'Management Ledger — Semantic Adjustments',
    'version': '17.0.11.1.0',
    'category': 'Management Ledger',
    'summary': 'Semantic management adjustments (Restatement, Regrouping, '
               'Adjustment JE) and the jito.ledger.trace provenance table.',
    'description': """
Management Ledger — Semantic Adjustments
=========================================

Phase 4 of the management-ledger feature (see docs/HLD.md and
docs/IMPLEMENTATION_PLAN.md §7).

Provides:
  * jito.ledger.trace — provenance join table per HLD §8.1 + Decision #4
    (two B-tree indexes; soft FK to account.move.line; immutable
    snapshot + source_payload_kind discriminator + payload registry).
  * jito.mgt.adjustment.je — FR-08: direct-author management JE with
    additive vs destructive reversal modes (destructive gated to
    senior+admin per PRD §Security Matrix).
  * jito.mgt.restatement — FR-06: re-categorize a specific LL line into
    a target MGT account; generates a balanced jito.ledger.move
    (entry_type=mgt_restate) plus trace rows linking back to source.
    17.0.4.0.0 added **cross-currency conversion**; 17.0.5.0.0 reshapes
    the UX so the **target currency is auto-derived** from the Final
    Destination account, and the user enters the **final amount** in
    that currency instead of a rate (rate is back-computed and tied to
    this single move — no global rate side-effect). FX still uses a
    clearing (``is_clearing``) FX-clearing account and preserves
    per-currency balance within the move (HLD §8.3). No FX revaluation
    JE is posted — rate
    drift surfaces at report time only (HLD FR-23).
  * jito.mgt.regrouping — FR-22: M:N split / merge in amount mode
    (17.0.3.0.0). Target lines carry per-target partner, accounting
    date, currency, and absolute amount. Strict-equality constraint
    enforces per-currency sum(targets) == abs(sum(sources)). Targets on
    different dates generate one jito.ledger.move per distinct date,
    each per-currency balanced.
  * snapshot_schemas.py — versioned snapshot schema registry (Decision #3).
  * payload_schemas.py — non-Odoo provenance kind registry (Decision #6).

All four semantic adjustments produce balanced jito.ledger.move output
via Phase 2's schema; this module owns the higher-level wizards and
the trace table.
""",
    'author': 'JITO LTD',
    'website': 'https://jito.dev',
    'license': 'LGPL-3',
    'depends': [
        'jito_ledger_nl',
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/record_rules.xml',
        'data/ir_sequence.xml',
        'views/jito_ledger_trace_views.xml',
        'views/jito_ledger_move_views.xml',
        'views/jito_mgt_restatement_views.xml',
        'views/jito_mgt_regrouping_views.xml',
        'views/jito_ledger_statutory_actions.xml',
        'views/jito_ledger_statutory_entry_view_inherit.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}

# jito_ledger_adjustments — Developer Guidance

## Module Purpose

`jito_ledger_adjustments` is **Phase 4** of the management-ledger
feature (see [`docs/HLD.md`](../../docs/HLD.md) and
[`docs/IMPLEMENTATION_PLAN.md`](../../docs/IMPLEMENTATION_PLAN.md) §7).

It delivers the four semantic management adjustments — Restatement,
Bridging, Regrouping, and Adjustment-JE-style destructive reversal —
plus the `jito.ledger.trace` provenance table that links generated
management lines back to their statutory sources.

All four semantic adjustments produce balanced
`jito.ledger.move(entry_type='mgt_*')` output via Phase 2's schema;
this module owns the higher-level wizards, the trace table, and
move-level extensions for FR-08 reversal modes.

---

## Scope summary

| FR | Concept | Where it lives |
|---|---|---|
| FR-06 | Restatement | `jito.mgt.restatement` |
| FR-07 + Spec | Bridging Lifecycle | `jito.mgt.bridging` (state: draft → open → cleared) |
| FR-22 | Regrouping (M:N, amount mode + per-target partner/date) | `jito.mgt.regrouping` + `jito.mgt.regrouping.target.line` |
| FR-08 | Adjustment JE w/ additive + destructive reversal | **Phase 2's `jito.ledger.move`** with `entry_type='mgt_adj_je'`. Additive reversal already in Phase 2; destructive added by this module. |
| FR-10/11/22 | Provenance traceability | `jito.ledger.trace` |

### Why no `jito.mgt.adjustment.je` model

The HLD originally proposed a wrapper model. We elide it: the wrapper
would carry the same metadata (memo, reason, reversal_state) we put
directly on `jito.ledger.move` via the inherited model in this module
(`models/jito_ledger_move.py`), and the discriminator-based pattern
(`entry_type='mgt_adj_je'`) already gives us everything we need
without parallel records. Users author adjustment-JE entries through
Phase 2's standard Journal Entries UI; this module just adds the
destructive-reverse action and the `reason` field.

---

## Models

### `jito.ledger.trace`

Provenance join table per HLD §8.1.

- `parallel_line_id` (M2O `jito.ledger.move.line`, required, cascade)
- `source_line_id` (M2O `account.move.line`, nullable, ondelete=set null)
- `source_snapshot` (Json, immutable) — frozen LL line state at trace
  creation per `snapshot_schemas.py` v1
- `snapshot_version` (Char, default `'1'`) — forward-compatible reader
- `source_payload_kind` + `source_payload` (hybrid) — for non-Odoo
  sources (Decision #6); `payload_schemas.py` registers the shape per kind
- `weight` (Float 0.0–1.0) — for regrouping splits
- `kind` — `derives_from | clears | bridges | reverses`

Two B-tree composite indexes per HLD Decision #4:
- `(source_line_id, kind)` — reverse lookup
- `(parallel_line_id, kind)` — forward lookup

Read-only via the UI; rows are created by the four `jito.mgt.*`
generators. Visible at **Management Ledger → Accounting → Adjustments →
Provenance Traces**.

### `jito.mgt.restatement` (FR-06)

Pick LL source line(s), pick a target MGT account, post → balanced
`jito.ledger.move(entry_type='mgt_restate')` plus trace rows.

**Form flow:**
1. Pick journal (must be linked to a non-leading or extension ledger).
2. Pick one or more `account.move.line` records as sources.
3. Pick the target MGT account (semantic_family = 'mgt').
4. Optional reason. Post.

**Generation logic (`_generate_move`):** branches on `is_fx_conversion`.

*Same-currency path (default):* per source line:
- FAAP-reversal line: opposite sign on the FAAP mirror of the source's
  account (looked up via `statutory_account_id`).
- MGT-target line: original sign on `target_account_id`.

*Cross-currency path (auto-activated when source currency ≠ target
account's `currency_id`; 17.0.5.0.0 UX):* the user enters the **Final
Amount** (`target_amount`) in the target currency; the system
back-computes `effective_fx_rate = abs(target_amount) / abs(source_net)`.
Per source line, four parallel lines so per-currency balance holds
within one move:

| Currency | Line | Amount |
|---|---|---|
| source | FAAP-reversal | `−src_signed` |
| source | FX clearing (`fx_clearing_account_id`) | `+src_signed` |
| target | MGT target (`target_account_id`) | `+src_signed × effective_rate` |
| target | FX clearing (`fx_clearing_account_id`) | `−src_signed × effective_rate` |

The effective rate is `abs(target_amount) / abs(source_net)` — back-
computed from the user's input, **scoped to this single move** (no
global `res.currency.rate` side-effect; two restatements on the same
date may legitimately use different rates). The FX clearing account
ends up with `+X` in source currency and `−X·R` in target currency;
valued at the same rate `R` in company currency they net to zero.
Later rate movements show up at report time via FR-23 presentation
translation — **no posted FX revaluation JE** (HLD line 60).

Required for the cross-currency path:
- All source lines must share one currency (enforced by
  `_check_fx_conversion`).
- Target account's `currency_id` must be set and differ from source
  currency (this is what auto-activates the FX path).
- `fx_clearing_account_id` (CLR.* family) must be set.
- `target_amount` must be non-zero at Post time.
- Net source amount must be non-zero (perfectly canceling sources
  rejected — rate would be undefined).
- The CLR-on-`mgt_restate` rule was relaxed in
  `jito_ledger_nl/models/jito_ledger_move_line.py:_check_account_semantic_rules`
  (17.0.5.4.0) so the four-line pattern doesn't trip the transit-only
  constraint.

Trace rows on all generated lines (2 or 4) link back to the source
with `kind='derives_from'`.

### `jito.mgt.bridging` (FR-07 + Spec Bridging Lifecycle)

Two-stage lifecycle: `draft → open (CLR pending) → cleared`.

**Stage 1 — Bridge** (`action_post`):
- Creates `jito.ledger.move(entry_type='mgt_bridge')` with FAAP-reversal
  + CLR-park lines per source. Trace `kind='bridges'`.
- Move state goes to `posted`; bridging state goes to `open`.

**Stage 2 — Clearance** (`action_clear`):
- Creates a second `jito.ledger.move(entry_type='mgt_bridge')` with
  CLR-clear + MGT-final lines, mirroring the bridge's CLR amounts.
- Trace `kind='clears'`; the `clearance_note` (downstream-event ref)
  is captured in `source_payload` (kind='manual_entry') for v1. A
  later release can elevate the downstream event to a typed payload.
- Move state goes to `posted`; bridging state goes to `cleared`.

Open CLR balances are listed under **Management Ledger → Accounting →
Adjustments → Open CLR Balances** (filtered tree on
`state == 'open'`).

### `jito.mgt.regrouping` (FR-22)

**17.0.3.0.0 — amount mode (no more weights).** Target lines carry an
absolute `amount` in a `currency_id`, an optional `partner_id`, and a
per-target `date`. Strict-equality constraint per HLD §5.5: per
currency, sum of `target_line_ids.amount` must equal the absolute sum
of source line amounts in that currency (exact match within
`currency.is_zero` tolerance).

**Target line fields** (`jito.mgt.regrouping.target.line`):
- `target_account_id` (M2O `jito.ledger.account`, required) — must be
  `semantic_family ∈ {'mgt', 'clr', 'faap'}`.
- `partner_id` (M2O `res.partner`, optional) — stamped on the generated
  MGT-side `jito.ledger.move.line` only. FAAP-reversal line keeps the
  source line's partner to preserve statutory traceability.
- `currency_id` (M2O `res.currency`, required, default = company currency).
- `amount` (Monetary, required) — absolute amount routed to this target.
- `date` (Date, required, default = parent regrouping's `date`).
- `name` (Char, optional label).

**Form flow:**
1. Pick journal.
2. Pick N source LL lines (Sources tab).
3. Define M target distributions (account + partner + date + currency
   + amount) in Target Distribution tab.
4. Verify the per-currency Sources Total / Targets Total summary in the
   footer turns green (`is_amounts_balanced == True`).
5. Post.

**Generation (`_generate_moves`):** target lines are grouped by `date`;
one `jito.ledger.move(entry_type='mgt_regroup')` is created per
distinct date. Each move contains, for every (source, target dated on
that day) pair where currencies match:

- One FAAP-reversal line at `−portion` on the source's FAAP mirror.
- One MGT line at `+portion` on `target.target_account_id`, with
  `partner_id = target.partner_id` (falls back to None if unset).

where `portion = source.amount_currency × (target.amount / sum_targets_in_currency)`.
Per-currency balance holds within each move because every MGT slice is
paired with its own FAAP reversal slice. Trace rows on both sides carry
`weight = ratio` (for backward compatibility with the trace-weight
column).

The parent `jito.mgt.regrouping` exposes `generated_move_ids` (Many2many)
to reach every generated move; `generated_move_id` keeps a pointer to
the first (earliest-dated) one. The form's **Generated Moves** tab
(visible only when `state == 'posted'`) lists them as a read-only tree.

**Reset to Draft** (17.0.3.1.0): the form header shows a
**Reset to Draft** button when posted. It deletes each generated move
(after putting them back to draft via the inherited move-level
`action_draft`) — lines cascade-delete, traces cascade with them.
Refuses if a generated move was reversed or destructively voided.

**Open after create** (17.0.3.1.0): the cog-menu **Regroup → Management
Ledger** actions on the statutory views now use `target='current'`
instead of opening in a modal, so the user lands directly on the new
regrouping's form.

### `jito.ledger.move` (extended)

This module inherits Phase 2's move and adds:

- `reason` (Char, tracking) — justification for management adjustments.
- `is_voided` + audit fields (`voided_by_uid`, `voided_at`,
  `voided_reason`) — destructive reversal state.
- `adjustment_origin` (Reference to the four semantic models) —
  navigation back to the wizard record.
- `action_reverse_destructive(reason=None)` — FR-08 mode (a). Gated
  to `group_mgmt_ledger_senior_accountant` or above per PRD §Security
  Matrix; raises `UserError` if a plain Accountant tries.

Voided moves stay in the database with full chatter audit but
display a red "Voided" ribbon on the form and are filterable in
search via the new "Voided" / "Active (not voided)" filters.
Phase 5 reports filter `is_voided=False` to hide them from
management views.

---

## Schema Registries

### `snapshot_schemas.py`

Versioned schema for `jito.ledger.trace.source_snapshot`. v1 ships
with the canonical LL line snapshot (`move_id`, `line_id`, `account_code`,
`debit`, `credit`, `amount_currency`, `currency_id`, `date`,
`partner_id`, `company_id` — see source for the full set).

`snapshot_account_move_line(line)` builds a v1 dict from a stock
`account.move.line` record.

Per HLD Decision #3: forward-compatible reader. New keys are additive
only; readers older than the new version see only the keys they know.

### `payload_schemas.py`

Per-kind schema for `jito.ledger.trace.source_payload`. v1 ships:
- `crypto_tx` — for `simple_crypto_accounting` integration
- `external_receipt` — out-of-band receipts
- `manual_entry` — pure management opinion (used by Bridging clearance
  in v1)

Downstream modules can register additional kinds via Odoo's
`selection_add` on `jito.ledger.trace.source_payload_kind`.

---

## Security

ACLs in `security/ir.model.access.csv`:
- `jito.ledger.trace`: read for all four mgmt-ledger groups; admin
  full CRUD (Phase 4 generators run as admin or via the action's
  ACL on the wizard).
- `jito.mgt.restatement` / `bridging` / `regrouping` /
  `regrouping.target.line`: all four groups have read+write+create+unlink
  per PRD §Security Matrix ("Create Management Adjustment ... ✅ across all
  four personas").
- Destructive reversal on `jito.ledger.move` is gated at the method
  level via `user.has_group('group_mgmt_ledger_senior_accountant')`.

Multi-company record rules on the new models in `security/record_rules.xml`.

---

## Menus

```
Management Ledger
└── Accounting
    ├── Journals (Phase 2)
    │   ├── Journal Entries
    │   └── Journal Items
    └── Adjustments              ← Phase 4
        ├── Restatements
        ├── Bridgings
        ├── Open CLR Balances    (filtered: state='open')
        ├── Regroupings
        └── Provenance Traces
```

The "Open CLR Balances" entry is a saved-filter view on
`jito.mgt.bridging` — quick access to bridges awaiting clearance.

---

## Verification Checklist (Phase 4)

After installing the module:

1. **Install completes** without errors.
2. **Adjustments submenu** appears at Management Ledger → Accounting →
   Adjustments with five children.
3. **Pre-test setup:** ensure FAAP mirrors exist for the LL accounts
   you'll bridge from / restate / regroup. (Run **Configuration → Chart
   of Accounts → FAAP Mirrors → Sync from Stock CoA** if not already.)
4. **Restatement** — Adjustments → Restatements → New. Pick journal,
   pick a posted LL line as source, pick an MGT target. Post. Verify:
   - A `jito.ledger.move(entry_type='mgt_restate')` appears in Journal
     Entries with two lines per source (FAAP reversal + MGT target).
   - Provenance Traces show two trace rows per source line, both
     linking to the LL source with `kind='derives_from'`.
5. **Bridging** — Adjustments → Bridgings → New. Pick journal, pick a
   posted LL move + lines, pick CLR + MGT accounts. **Bridge (Stage 1)**.
   Verify state = `open` and a `mgt_bridge` move exists with FAAP →
   CLR posting. CLR balance now non-zero in Journal Items grouped by
   account. Then fill **Clearance Reference** and click **Clear (Stage 2)**.
   Verify state = `cleared`, second `mgt_bridge` move exists with CLR →
   MGT, CLR balance back to zero.
6. **Regrouping** (17.0.3.0.0 — amount mode) — Adjustments →
   Regroupings → New. Pick journal, pick N source lines, define M
   target distributions (account + partner + accounting date + currency
   + amount). The footer's per-currency Sources Total / Targets Total
   turns green once amounts balance. **Post**. Verify:
   - One `jito.ledger.move(entry_type='mgt_regroup')` is generated **per
     distinct target date** (a 2-date split → 2 moves).
   - On each move: per (source, target-on-this-date) pair there is one
     FAAP-reversal line and one MGT line on the target's account; the
     MGT line carries `partner_id = target.partner_id`, while the FAAP
     reversal keeps the source's partner.
   - Try posting with target amounts that don't equal source totals in
     some currency → strict-equality constraint rejects.
7. **Destructive reversal** — open a posted `mgt_adj_je` move (or any
   `jito.ledger.move`); fill `reason`; click **Destructive Reverse**.
   As Senior Accountant or Admin: succeeds, ribbon appears. As plain
   Accountant: rejected with the "Senior Accountant or higher" message.
8. **Provenance Traces** menu — read-only browse of all trace rows;
   filter by kind, group by source move.

---

## Out of scope (deferred to Phase 5 / v1.x)

- **Combined-view P&L / Balance Sheet** (Phase 5).
- **Auto-detected clearance** — clearance is manual in v1; auto-matching
  CLR balances against downstream events (e.g., crypto tx ingestion)
  is post-v1 (PRD §Out of Scope).
- **Aging report on open CLR balances** — basic state filter only;
  formal aging report is Phase 5 / v1.x.
- **Typed downstream-event payload on clearance traces** — currently
  `manual_entry` with a memo; could be elevated to a typed kind
  (`crypto_tx` etc.) referencing real downstream records in v1.x.
- **Cross-currency restatement / regrouping** — assumes source and
  target use the same currency. Multi-currency restatement is a v1.x
  improvement.

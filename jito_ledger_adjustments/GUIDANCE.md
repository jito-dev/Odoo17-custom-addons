# jito_ledger_adjustments — Developer Guidance

## Module Purpose

`jito_ledger_adjustments` is **Phase 4** of the management-ledger
feature (see [`docs/HLD.md`](../../docs/HLD.md) and
[`docs/IMPLEMENTATION_PLAN.md`](../../docs/IMPLEMENTATION_PLAN.md) §7).

It delivers the semantic management adjustments — Restatement,
Regrouping, and Adjustment-JE-style destructive reversal — plus the
`jito.ledger.trace` provenance table that links generated management
lines back to their statutory sources.

> **Bridging removed (17.0.11.0.0).** The former Bridging feature
> (FR-07) — the `jito.mgt.bridging` model, its wizard/views/menu/ACLs/
> sequence/record-rule, and the "Bridge" buttons/smart-button/actions on
> the statutory views — was deleted in its entirety. The `mgt_bridge`
> `entry_type` value and the trace `kind` values `'bridges'`/`'clears'`
> are **kept as inert Selection values** purely so existing posted data
> stays loadable; no Bridging feature exists anymore.

All the semantic adjustments produce balanced
`jito.ledger.move(entry_type='mgt_*')` output via Phase 2's schema;
this module owns the higher-level wizards, the trace table, and
move-level extensions for FR-08 reversal modes.

---

## Scope summary

| FR | Concept | Where it lives |
|---|---|---|
| FR-06 | Restatement | `jito.mgt.restatement` |
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
- `kind` — `derives_from | reverses` (the `bridges`/`clears` values are
  retained as inert Selection members for existing-data safety only; see
  the Bridging-removed note above)

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
- `fx_clearing_account_id` (a clearing account, `is_clearing=True`) must be set.
- `target_amount` must be non-zero at Post time.
- Net source amount must be non-zero (perfectly canceling sources
  rejected — rate would be undefined).
- Clearing accounts (`is_clearing`) are freely postable — the former
  entry-type restriction in `jito_ledger_nl` (which only allowed a
  narrow entry-type set) was removed in 17.0.13.2.0, so the four-line
  FX pattern (and bank-rec / crypto flows) post without issue.

Trace rows on all generated lines (2 or 4) link back to the source
with `kind='derives_from'`.

### Partial consumption (17.0.11.0.0)

Both Restatement and Regrouping can now consume only **part** of a
source statutory line. The un-consumed remainder stays fully re-pickable
by a **later restatement OR regrouping** — consumption is shared across
both adjustment types.

**Mechanism (double-entry-derived).** A partial adjustment reverses only
the *consumed slice* of the source's FAAP projection (rather than its
whole amount). There is **no stored consumed field**: "consumed" for a
statutory line is defined as the sum of the FAAP-reversal postings booked
against that line's OWN FAAP mirror. It is computed live from the trace
table via the batch helpers:

- `jito.ledger.trace.consumed_by_source(...)` — consumed amount per
  source line.
- `jito.ledger.trace.remaining_to_adjust(...)` — source amount minus
  consumed, per source line.

The same figures are surfaced in `jito_ledger_nl` on the **Statutory
Journal Items** list as the `consumed_currency` / `remaining_currency` /
`adjustment_status` columns, with **Unadjusted / Partially / Fully**
search filters.

**UX — per-source consume rows.** Each wizard gained a
`source_consume_ids` sub-model:

- `jito.mgt.restatement.source.line` and
  `jito.mgt.regrouping.source.line`, both sharing
  `jito.mgt.source.consume.mixin`.
- Each row is an editable per-source line with:
  - `move_line_id` — the statutory source line.
  - `source_amount_currency` (readonly) — the source line's own amount.
  - `remaining_display` (readonly) — the live remaining-to-adjust.
  - `consume_amount` (editable, default = remaining) — how much of this
    source to consume in this adjustment.
- The legacy invisible M2M `source_line_ids` is **kept and synced both
  ways**: the statutory cog launch sets the M2M → an onchange
  materialises the consume rows; at post `_ensure_consume_rows`
  reconciles the M2M and the consume rows so neither drifts.

**Generation.** Only the consumed slice is reversed/booked (not the full
source amount). The resulting trace `weight` equals the *consumed
fraction* of the source. For regrouping, the strict-equality constraint
now requires, per currency,
`sum(targets) == abs(sum(consumes))`. Over-consumption is
**hard-blocked at post** (`_check_consume_within_remaining`, which
re-reads the remaining live so concurrent adjustments cannot overspend a
source). Partial consumption combined with a **Matched Destination
Entry** (restatement matched mode) is blocked in v1.

**Preview parity (17.0.11.1.0).** `_build_preview_lines` uses the exact
same `_consume_map()` / `_consume_signed()` path as `_generate_move`, so the
draft Preview already reflects the **Consume** slice (FAAP-reversal, both
FX-clearing legs, and the FX-converted MGT target all scale with it). Two
robustness fixes: (1) `_consume_map`'s fallback for a source line without a
materialised consume row now uses that line's **remaining** (via
`remaining_to_adjust`), never the full amount — so a first render right after
the cog launch can't briefly show the whole line; (2) the Preview now also
renders the **Realization (FX delta)** counter + P&L rows that
`_generate_move` emits, so an FX restatement with realization previews
identically to what posts. The realization delta itself is scaled by the
consume fraction in `_calc_realization_delta`, so the Preview and the
Realization tab both reflect the consumed slice, not the whole source.

### `jito.mgt.regrouping` (FR-22)

**17.0.3.0.0 — amount mode (no more weights).** Target lines carry an
absolute `amount` in a `currency_id`, an optional `partner_id`, and a
per-target `date`. Strict-equality constraint per HLD §5.5: per
currency, sum of `target_line_ids.amount` must equal the absolute sum
of source line amounts in that currency (exact match within
`currency.is_zero` tolerance). With partial consumption (17.0.11.0.0)
the source side is the consumed amount, so the constraint becomes
`sum(targets) == abs(sum(consumes))` per currency.

**Target line fields** (`jito.mgt.regrouping.target.line`):
- `target_account_id` (M2O `jito.ledger.account`, required) — must be an
  MGT.* or FAAP.* account (`semantic_family ∈ {'mgt', 'faap'}`), or any
  account flagged `is_clearing=True`. Domain:
  `['|', ('semantic_family','in',['mgt','faap']), ('is_clearing','=',True)]`.
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
- `manual_entry` — pure management opinion

Downstream modules can register additional kinds via Odoo's
`selection_add` on `jito.ledger.trace.source_payload_kind`.

---

## Security

ACLs in `security/ir.model.access.csv`:
- `jito.ledger.trace`: read for all four mgmt-ledger groups; admin
  full CRUD (Phase 4 generators run as admin or via the action's
  ACL on the wizard).
- `jito.mgt.restatement` / `regrouping` /
  `regrouping.target.line` (and the `*.source.line` consume sub-models):
  all four groups have read+write+create+unlink
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
        ├── Regroupings
        └── Provenance Traces
```

---

## Verification Checklist (Phase 4)

After installing the module:

1. **Install completes** without errors.
2. **Adjustments submenu** appears at Management Ledger → Accounting →
   Adjustments with three children.
3. **Pre-test setup:** ensure FAAP mirrors exist for the LL accounts
   you'll restate / regroup. (Run **Configuration → Chart of Accounts →
   FAAP Mirrors → Sync from Stock CoA** if not already.)
4. **Restatement** — Adjustments → Restatements → New. Pick journal,
   pick a posted LL line as source, pick an MGT target. Post. Verify:
   - A `jito.ledger.move(entry_type='mgt_restate')` appears in Journal
     Entries with two lines per source (FAAP reversal + MGT target).
   - Provenance Traces show two trace rows per source line, both
     linking to the LL source with `kind='derives_from'`.
5. **Regrouping** (17.0.3.0.0 — amount mode) — Adjustments →
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
     some currency → strict-equality constraint rejects (for a partial
     regrouping the equality is `sum(targets) == abs(sum(consumes))`).
6. **Partial consumption** (17.0.11.0.0) — restate or regroup only PART
   of a source line: launch the wizard from the statutory cog, then in
   the per-source consume row lower `consume_amount` below
   `remaining_display`. Post. Verify:
   - The generated move reverses/books only the consumed slice, and the
     trace `weight` equals the consumed fraction.
   - On the **Statutory Journal Items** list (jito_ledger_nl) the source
     shows `consumed_currency` / `remaining_currency` and
     `adjustment_status = Partially`; the remainder is re-pickable by a
     later restatement OR regrouping.
   - Re-open and try to consume more than the live remaining → hard-
     blocked at post (`_check_consume_within_remaining`).
7. **Destructive reversal** — open a posted `mgt_adj_je` move (or any
   `jito.ledger.move`); fill `reason`; click **Destructive Reverse**.
   As Senior Accountant or Admin: succeeds, ribbon appears. As plain
   Accountant: rejected with the "Senior Accountant or higher" message.
8. **Provenance Traces** menu — read-only browse of all trace rows;
   filter by kind, group by source move.

---

## Out of scope (deferred to Phase 5 / v1.x)

- **Combined-view P&L / Balance Sheet** (Phase 5).
- **Partial + Matched Destination Entry** (restatement matched mode) —
  combining partial consumption with a matched destination entry is
  blocked in v1.
- **Cross-currency restatement / regrouping** — assumes source and
  target use the same currency. Multi-currency restatement is a v1.x
  improvement.

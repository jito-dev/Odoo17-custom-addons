# jito_ledger_nl — Developer Guidance

## Module Purpose

`jito_ledger_nl` is **Phase 2** of the management-ledger feature
(see [`docs/HLD.md`](../../docs/HLD.md) and
[`docs/IMPLEMENTATION_PLAN.md`](../../docs/IMPLEMENTATION_PLAN.md) §5).

It introduces the **single shared parallel-entry table** that hosts:
- **Non-Leading Ledger documents** (entry_type = `nl_doc`) — Phase 2's
  primary deliverable;
- **Extension Ledger adjustments** (entry_type = `ext_adjustment`) —
  consumed by Phase 3;
- the four **Management Adjustment outputs** (entry_type = `mgt_restate`
  / `mgt_bridge` / `mgt_regroup` / `mgt_adj_je`) — produced by Phase 4.

A single schema serves all six concerns (per HLD §4.3 + Decision #4),
with `entry_type` as the discriminator.

This module ships **no FK from any jito_ledger_\* table into
account.move\***. The parallel-record model (FR-13) is enforced at the
schema level: there is physically no path for management-layer code to
write into stock Odoo's accounting tables.

---

## Architecture Overview

### One table, many shapes

```
jito.ledger.move
  ├── entry_type = nl_doc            ← NL documents (Phase 2)
  ├── entry_type = ext_adjustment    ← Extension adjustments (Phase 3)
  ├── entry_type = mgt_restate       ← Restatement output (Phase 4)
  ├── entry_type = mgt_bridge        ← Bridging output (Phase 4)
  ├── entry_type = mgt_regroup       ← Regrouping output (Phase 4)
  └── entry_type = mgt_adj_je        ← Adjustment-JE output (Phase 4)
```

Each row uses the same fields, the same constraints, and the same
state machine. `entry_type` lets reports (Phase 5) filter by purpose
without a multi-table union.

### Currency model

Per HLD Decision #8, lines store **transaction currency only**:
- `currency_id` (M2O `res.currency`)
- `amount_currency` (signed Float — positive = debit-side, negative =
  credit-side)

There are **no** `debit / credit / balance` company-currency columns.
The presentation translation to company currency happens at report
time (Phase 5) using `res.currency._get_query_currency_table()`. This
is strict alignment with FR-23 — no rate snapshot at post date.

For UX, the form's line tree exposes display-only `debit_amount_currency`
and `credit_amount_currency` columns, both in **transaction currency**.

### Per-currency balancing

Per HLD Decision #10, the balanced-JE invariant is **per-currency**: for
each `currency_id` present in a move's lines, the sum of
`amount_currency` must net to zero. A move with USDC and EUR lines must
balance USDC against USDC and EUR against EUR independently.

The constraint is enforced on `state != 'draft'` so users can edit
draft entries without tripping it; `action_post()` runs it explicitly
before the transition.

### Period-lock inheritance

Per HLD Decision #12, NL Ledger respects the same `fiscalyear_lock_date`
and `period_lock_date` that stock `account.move` uses. The
`_check_fiscalyear_lock_date()` method mirrors the stock pattern at
`odoo17_enterprise/odoo/addons/account/models/account_move.py:1956-1965`,
calling `move.company_id._get_user_fiscal_lock_date()` to get the
group-aware lock date and rejecting any post on or before that date.

Group behaviour:
- `account.group_account_manager` users (Sr.Acct, FM, Admin in our
  matrix) are bound only by `fiscalyear_lock_date`;
- plain accountants are bound by `max(period_lock_date, fiscalyear_lock_date)`.

Tax-lock dates are **not** enforced — NL is out of scope for tax
(FR-15).

---

## Main Models

### `jito.ledger.move`

**File:** `models/jito_ledger_move.py`

**Purpose:** parallel-ledger journal entry; one row = one balanced
multi-currency entry.

**Key fields:**

| Field | Type | Notes |
|---|---|---|
| `name` | Char (required) | Default `'New'`; assigned by sequence on first post. |
| `ref` | Char | Free-text reference. |
| `ledger_id` | M2O `jito.ledger` (required) | Domain restricts to `kind in ['non_leading', 'extension']`. The Leading Ledger has its own table (`account.move`); this model only ever holds non-leading and extension entries. |
| `entry_type` | Selection (required) | Discriminator. Default `nl_doc`. |
| `state` | Selection | `draft` → `posted` → `reversed`. |
| `date` | Date (required, default today) | Used for the period-lock check. |
| `partner_id` | M2O `res.partner` | Optional. |
| `currency_id` | M2O `res.currency` | Optional document-level hint; line-level `currency_id` is what matters for balancing. For invoice-style `move_type` (`out_invoice` / `out_refund` / `in_invoice` / `in_refund`) `default_get` pre-fills it with `env.company.currency_id`, so the simplified invoice/bill forms always render with a currency picked. |
| `line_ids` | One2many | The lines. |
| `source_move_id` | M2O `account.move` (`ondelete='set null'`) | Soft FK for traceability. **Read-only.** Never written into. |
| `reversed_entry_id` | M2O self | If set, this row is the additive counter-entry of the row it points to. |
| `reversal_move_ids` | One2many self | The counter-entries that reversed this move. |

**Mixins:** `mail.thread`.

**Workflow methods:**

| Method | Effect |
|---|---|
| `action_post()` | Runs the period-lock check; assigns sequence number if `name == 'New'`; transitions to `posted`. The per-currency balance constraint fires automatically via `@constrains` on `state` change. |
| `action_draft()` | Posted → draft. Refused if the move was reversed or if the move is itself a counter-entry (would orphan the original). |
| `action_reverse()` | Creates a counter-entry with negated `amount_currency` lines, auto-posts it, flags the original `reversed`. Both rows stay visible (additive reversal — destructive reversal is Phase 4). |

**Constraints:**

| Constraint | Trigger | Why |
|---|---|---|
| `_check_balanced_per_currency` | `state != 'draft'`; `line_ids` change | HLD Decision #10 — per-currency balancing. |
| `_check_ledger_company` | `ledger_id`, `company_id` | The move and its ledger must share company. |
| `_check_reversal_link` | `reversed_entry_id` | A move cannot reverse itself. |

**Guards:**

- `@api.ondelete` on the model: only draft moves may be deleted. Posted
  or reversed moves must be reversed via `action_reverse` instead.

### `jito.ledger.move.line`

**File:** `models/jito_ledger_move_line.py`

**Purpose:** line under `jito.ledger.move`.

**Key fields:**

| Field | Type | Notes |
|---|---|---|
| `move_id` | M2O (required, cascade) | Parent move. |
| `ledger_id` | related, stored, indexed | Mirror of `move_id.ledger_id`. Structural ledger isolation (HLD §8.3). |
| `account_id` | M2O **`jito.ledger.account`** (required) | NOT `account.account` — Decision #13. |
| `account_semantic_family` | related, stored | `faap` / `mgt` / `clr` / `grp`. |
| `partner_id`, `name` | Standard | Optional. |
| `currency_id` | M2O `res.currency` (required, precompute) | Transaction currency for the line. `_compute_currency_id` (precompute, `store=True`, `readonly=False`) inherits from `move_id.currency_id` when the line is created without one — the form's `default_currency_id` context still wins when present. Guarded so a user-picked line currency is preserved if the move's currency later changes (HLD Decision #10: lines may use different currencies; balancing is per-currency). |
| `amount_currency` | Monetary (signed) | Positive = debit-side; negative = credit-side. |
| `debit_amount_currency` / `credit_amount_currency` | Monetary (computed, display-only) | Split-side display in transaction currency, NOT company currency. |
| `amount_residual_currency` | Monetary | **Reserved per HLD Decision #11.** Not used in v1; reconciliation logic ships in v1.x. |
| `reconciled` | Boolean | **Reserved per HLD Decision #11.** Not used in v1. |

**Constraints:**

| Constraint | Why |
|---|---|
| `_check_account_semantic_rules` | GRP.* accounts are non-posting (HLD §4.4). CLR.* accounts allowed when `entry_type in ('mgt_bridge', 'mgt_restate')` — the restate case is FX-clearing for cross-currency restatement (17.0.5.4.0). Anything else with a CLR account is rejected so the transit-only invariant holds. |
| `_check_account_company` | Account must belong to the line's company. |
| `_check_nonzero_amount` | A zero-amount line carries no information; reject. |

**Note on `account_id` company filter:** the field declares
`check_company=True`, so Odoo's framework auto-filters dropdown options
to the parent move's company.

---

## Business Logic

### Posting flow

```
draft → action_post() →
  1. Check state == draft (else UserError)
  2. Check line_ids non-empty (else UserError)
  3. _check_fiscalyear_lock_date() (UserError if move.date <= lock)
  4. Assign sequence number if name == 'New'
  5. write({'state': 'posted'})
       └ triggers _check_balanced_per_currency (ValidationError if unbalanced)
       └ triggers per-line _check_account_semantic_rules
```

If any check fails, the transition is rolled back and the move stays
draft.

### Reversal (additive only in v1)

```
posted → action_reverse() →
  1. Check state == posted, no prior reversal
  2. Create counter-move: same ledger_id, entry_type, partner;
     date = today; lines have negated amount_currency
  3. counter.action_post() (sequence number, period-lock, balance)
  4. original.write({'state': 'reversed'})
  5. message_post() on both for chatter visibility
```

Both the original and the counter stay visible. **Destructive
reversal** (where the original disappears from reports) is FR-08 mode
(a) and lives in Phase 4 on `jito.mgt.adjustment.je`.

### Sequence

`data/ir_sequence.xml` ships an `ir.sequence` with code
`jito.ledger.move`, prefix `JLM/<year>/`, padding 5. Global (no
`company_id`) for v1 — per-company numbering can be added later if
required.

---

## Security

### ACLs

`security/ir.model.access.csv` per PRD §Security Matrix:

| Group | jito.ledger.move | jito.ledger.move.line |
|---|---|---|
| `group_mgmt_ledger_accountant` | read+write+create+unlink | read+write+create+unlink |
| `group_mgmt_ledger_senior_accountant` | read+write+create+unlink | read+write+create+unlink |
| `group_mgmt_ledger_finance_manager` | **read only** | **read only** |
| `group_mgmt_ledger_admin` | full | full |

Note: Finance Manager is **read-only** on NL moves per the PRD matrix
("Post to Non-Leading Ledger" → ❌ for CFO/FM). The expected workflow
is FM uses `jito.mgt.*` semantic adjustments (Phase 4) for any
ledger-touching operation; daily NL bookkeeping is the Accountant /
Senior Accountant role.

The `_unlink_only_drafts` guard on the model means even users with
unlink rights cannot remove posted or reversed moves — they must use
`action_reverse` instead.

### Record rules

`security/record_rules.xml` — multi-company scoping on both new models.
Visible records are filtered by `company_id IN company_ids`.

### Schema-level FR-02

LL immutability is enforced by the **absence** of any FK from
`jito_ledger_*` tables into `account.move*`. Records in this module
**cannot** write into stock Odoo's accounting tables; the worst a
buggy migration could do is corrupt the management layer, never the
statutory ledger.

---

## Views & Menu

### Menu integration

```
Management Ledger              (top-level, from jito_ledger_core)
├── Ledgers
├── Chart of Accounts
└── Journal Entries            ← added by jito_ledger_nl (sequence 30)
```

### Form view highlights

- Statusbar: `draft → posted → reversed` with action buttons.
- Header buttons: **Post**, **Reset to Draft** (only for posted, not
  reversed, not counter-entry), **Reverse Entry**.
- Stat button: "Reversals" — visible if the move has been reversed,
  links to the counter-entry.
- Line editor: tree-form style; debit/credit columns in tx currency.
- Domain on `account_id`: filters out `GRP.*` accounts (constraint also
  catches it server-side).

### Search filters

By state (draft / posted / reversed), entry_type (NL / Extension /
Management), date range, and group-by ledger / entry_type / state /
date. Default search filter on install: `state == 'posted'`.

---

## Integration Guidelines

### For Phase 3 (`jito_ledger_extension`)

Extension Ledger adjustments are `jito.ledger.move` rows with
`entry_type='ext_adjustment'`. The schema already supports them; Phase
3 adds combined-view query helpers and ext-adjustment-specific UX (a
"Create Extension Adjustment" button on extension ledgers).

No schema changes needed in this module.

### For Phase 4 (`jito_ledger_adjustments`)

Each `jito.mgt.*` semantic model creates `jito.ledger.move` rows with
the corresponding `entry_type` (`mgt_restate`, `mgt_bridge`,
`mgt_regroup`, `mgt_adj_je`). The CLR.\*-only-from-mgt_bridge
constraint already in this module is the foundation Phase 4 builds on;
Phase 4 adds the `jito.ledger.trace` table and the four semantic-
adjustment models that drive `_generate_move()`.

The `source_move_id` field on `jito.ledger.move` is read-only here but
populated by Phase 4 helpers when an adjustment derives from an LL
move.

### For Phase 5 (`jito_ledger_reports`)

The report custom handler will query `jito.ledger.move.line` directly,
joining `account.account` for LL data and `jito.ledger.account` for
management-layer data. Currency translation uses
`amount_currency` + `currency_id` and `res.currency._get_query_currency_table`.

There is no cached `debit/credit/balance` to read — every report run
applies the rate table.

---

## Verification Checklist (Phase 2)

After installing the module:

1. **Install completes** without errors.
2. **Menu present**: Management Ledger → Journal Entries (sequence 30,
   between Chart of Accounts and any future Configuration).
3. **Prerequisite — create an NL ledger.** Phase 1 doesn't auto-seed
   one (NL is optional per FR-03). Management Ledger → Ledgers → New →
   Kind: Non-Leading; save.
4. **Create a balanced single-currency move.** Journal Entries → New;
   pick the NL ledger; entry_type `nl_doc`; add two USDC lines:
   - Line 1: account `FAAP.ROOT`, amount 100.00 (debit-side)
   - Line 2: account `MGT.ROOT`, amount -100.00 (credit-side)
   Press **Post**. ✓ Should succeed; sequence assigns a JLM/yyyy/00001
   number.
5. **Per-currency balance enforcement.** New move; add USDC 100 + USDC
   -50 + EUR 100 (no offsetting EUR). Try Post → ValidationError naming
   the EUR currency.
6. **Multi-currency balanced move.** New move; USDC 100 / -100 + EUR
   50 / -50. Post → succeeds.
7. **GRP.* posting forbidden.** New move; pick `GRP.ROOT` on a line —
   the line's domain hides it; if forced server-side, ValidationError.
8. **CLR.* posting allowed only from mgt_bridge.** New move; pick
   `CLR.ROOT` with entry_type `nl_doc`; try Post → ValidationError. Set
   entry_type to `mgt_bridge`; Post → succeeds (or at least the
   semantic constraint passes; balance still required).
9. **Period-lock inheritance.** Stock Accounting → Configuration →
   Settings → Lock Date → set "All Users Lock Date" to today. Open the
   NL move you posted earlier; try `Reset to Draft` and re-post → the
   `_post()` call raises UserError mentioning the lock date. As an
   account manager (Sr.Acct / FM / Admin), only `fiscalyear_lock_date`
   blocks; as a plain Accountant, both lock dates apply.
10. **Reversal flow.** Open a posted move; press **Reverse Entry**.
    Counter-entry appears with state=posted and the original is now
    state=reversed. The "Reversals" stat button on the original links
    to the counter.
11. **Stock CoA untouched.** Open Accounting → Customers / Invoices.
    Run any normal flow. No row of `account.move` was created by NL
    activity. Quick SQL check (if you have shell access):
    `SELECT COUNT(*) FROM account_move;` — same before and after NL
    operations.
12. **Permission check.** As a user in `group_mgmt_ledger_finance_manager`
    only (no senior or admin), open Journal Entries — list visible,
    "New" button absent / disabled, posting buttons hidden.

---

## Out of scope (deferred)

- **NL-specific invoice / vendor bill / payment specialized forms** —
  basic move CRUD covers FR-13's lifecycle minimum. Specialized UX may
  ship in a Phase 2.5.
- **Reconciliation matching logic** — Decision #11 reserves the schema
  fields (`amount_residual_currency`, `reconciled`); matching code
  ships in v1.x.
- **Destructive reversal** — Phase 4 territory on `jito.mgt.adjustment.je`.
- **Source-line traceability table** (`jito.ledger.trace`) — Phase 4.
- **Per-company sequence numbering** — global sequence in v1.

For the rest of the v1 trajectory, see [`docs/IMPLEMENTATION_PLAN.md`](../../docs/IMPLEMENTATION_PLAN.md).

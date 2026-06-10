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

### Currency model (17.0.10.0.0 — ADR reversed Decision #8)

Lines now store **both** the transaction-currency amount AND a
company-currency snapshot frozen at posting time:

- **Tx currency**: `currency_id` (M2O `res.currency`), `amount_currency`
  (signed Float — positive = debit-side, negative = credit-side),
  `debit_amount_currency` / `credit_amount_currency` (display-only
  split, in tx currency).
- **Company currency (NEW)**: `company_currency_id` (related from move),
  `balance` (Monetary, computed by `_compute_balance` from
  `amount_currency × _convert(... line.date)`, stored, readonly=False
  so creators can override), `debit` / `credit` (the ±split of balance,
  with inverse so editing one column round-trips correctly).

**Why the reversal of Decision #8 / FR-23?** The original "FX is
presentation only, no rate snapshot" rule worked for single-currency
moves but failed for multi-currency moves (Restatement, Bridging,
Regrouping). At report time, each currency was translated independently
via `res.currency.rate`, so a CLR pair calibrated against an effective
rate at posting drifted apart whenever Odoo's two market rates
implied a different cross-currency ratio — producing a CLR residual
that was a pure rate-mismatch artifact, not an economic event. See
the 17.0.10.0.0 ADR for the full discussion.

Calibrated multi-currency creators (Restatement's FX path in
`jito_ledger_adjustments`) pass an explicit `balance` value in the
`Line.create()` vals so the CLR pair balances cleanly in company
currency. Single-currency creators (NL invoices, Bridging,
Regrouping) omit the explicit balance — the default `_compute_balance`
translation handles them correctly because each pair stays within
one currency.

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
| `amount_residual_currency` | Monetary (computed, stored) | Open balance on the line in transaction currency. Computed from `amount_currency` minus matched partial-reconcile amounts. Equals `amount_currency` for non-posted or non-reconcilable accounts. **Active since 17.0.7.0.0** (HLD Decision #11). |
| `reconciled` | Boolean (computed, stored, indexed) | `True` when `amount_residual_currency` rounds to zero in the line's currency. **Active since 17.0.7.0.0**. |
| `matched_debit_ids` | O2M → `jito.ledger.partial.reconcile` (inverse `credit_line_id`) | Partials where this (credit) line is matched against a debit. |
| `matched_credit_ids` | O2M → `jito.ledger.partial.reconcile` (inverse `debit_line_id`) | Partials where this (debit) line is matched against a credit. |

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

### Reconciliation (17.0.7.0.0 — HLD Decision #11)

**Model:** `jito.ledger.partial.reconcile`. Pairs one debit
move-line with one credit move-line on the **same account** and
**same currency**, carrying the matched amount in that currency.

```
DR line (residual > 0) ──┐
                         ├── partial.reconcile (amount, currency)
CR line (residual < 0) ──┘
```

**Eligibility.** `jito.ledger.account` carries a `reconcile`
Boolean (added in `jito_ledger_core` 17.0.2.3.0). Auto-defaults to
True for `account_type in ('asset_receivable', 'liability_payable')`
and for the CLR family; toggleable per-account.

**Algorithm** (`JitoLedgerMoveLine._reconcile`): greedy two-pointer
walk over `(debits_sorted_by_date, credits_sorted_by_date)`. Each
step creates one partial for `min(debit_residual, |credit_residual|)`
and advances whichever side fully closed. The dependency chain
(`@api.depends('matched_*_ids.amount', ...)`) automatically updates
`amount_residual_currency` and flips `reconciled` when residual
rounds to zero in the line currency.

**Invoice payment status.** `jito.ledger.move.payment_state` is a
stored compute (`not_paid` / `in_payment` / `paid` / `reversed`)
derived from the move's payment-term line(s):
* All payment-term lines `reconciled=True` → `paid`
* Any payment-term line has at least one matched partial → `in_payment`
* Else → `not_paid`

Only invoice-type moves (`out_invoice` / `out_refund` / `in_invoice` /
`in_refund`) compute a meaningful value; other types stay
`not_paid`.

**UX flow:**

1. Open **Management Ledger → Accounting → Journals → Journal
   Items**, filter by the receivable / clearing account, partner, or
   the new **Unreconciled (Open)** filter.
2. Select the debit + credit lines you want to match.
3. Action menu → **Reconcile Selected Lines** → preview the per-
   currency totals and net → **Reconcile**.
4. To undo: select the same lines → **Remove Reconciliation**.

**Reset to draft.** `action_draft` refuses on moves whose lines carry
any matched partial — unreconcile first, otherwise residuals on the
counterparty would silently drift.

**Audit:** all partials are listed under **Management Ledger →
Accounting → Journals → Reconciliations**.

### Bank Reconciliation Widget UX (17.0.8.2.0 — stock-style rewrite)

Two-pane layout, accessed via the **Reconcile X items** button on the
journal kanban card:

* **Left pane** — kanban of open bank-side `jito.ledger.move.line`
  records. Click a card to open the right pane.
* **Right pane** — form view of a transient `jito.bank.rec.widget`
  bound to the picked bank line. Layout mirrors stock's
  `account_accountant` reconciliation widget:
  1. Statusbar buttons: **Validate** (enabled when balanced) /
     **Reset** (clears picks).
  2. **Unified top table** (`o_bank_rec_lines_widget_table`):
     liquidity row + each picked counterpart + the auto-balance
     suspense row. The suspense account is the journal's
     `suspense_account_id` (falls back to the company's first
     `CLR.*` account). Click the trash icon on a counterpart row to
     remove it.
  3. **Notebook**:
     - **Match Existing Entries** — searchable list of open posted
       lines (same currency, reconcilable account, partner-aware).
       **Click a row to add it as a counterpart**; click again to
       remove. Highlighted rows are already picked.
     - **Manual Operations** — placeholder (deferred).
     - **Discuss** — pointer to the source journal entry chatter.

**Click-to-add wiring** (17.0.8.2.0). The AMLs list is mounted via the
custom field widget `jito_bank_rec_amls` (see
`static/src/components/bank_reconciliation/amls_list_view.js`). The
widget subclasses `X2ManyField` and swaps in
`JitoBankRecAmlsRenderer` so `onCellClicked` actually fires on the
embedded tree. Without this, `js_class` on the inline `<tree>` is
silently dropped by `X2ManyField` and clicks do nothing.

**Auto-bridging on Validate** (17.0.8.5.0). The original implementation
created a direct `jito.ledger.partial.reconcile` between the bank line
and each picked counterpart, which works only when the two lines are
on opposite sides (one DR, one CR). For the common crypto-receipt
scenario (`DR DeFi Wallet` matched against an open
`DR MGT.RECEIVABLE`), both lines are debit — the partial-reconcile
DR>0 / CR<0 invariant rejects them.

`action_validate` now partitions the picks into *direct* (opposite
side, single partial each — fast path, unchanged) and *same-side*
(needs bridging). For same-side picks it auto-posts a balanced
bridging `jito.ledger.move` whose lines re-route the open balance
through the bank move's counter-account, then reconciles both legs:

```
Original AR invoice line:  DR MGT.RECEIVABLE       +X       (open)
Original DeFi receipt:     DR MGT.DEFIWALLET.*     +X       (open)
                           CR MGT.DEFI_INCOME      -X       (open)

Bridging move (auto-posted on Validate):
                           CR MGT.RECEIVABLE       -match
                           DR MGT.DEFI_INCOME      +match

Reconciles created:
  AR side:        original DR MGT.RECEIVABLE  ↔  bridging CR MGT.RECEIVABLE
  Counter side:   original CR MGT.DEFI_INCOME ↔  bridging DR MGT.DEFI_INCOME
                  (skipped if MGT.DEFI_INCOME is not reconcilable —
                  the AR side still closes cleanly)
```

Restrictions: the bank line's move must have exactly one counter-line
in the same currency (clean two-line receipts) and that counter-line
must not already be fully reconciled. If either fails, Validate raises
a `UserError` with the suggested manual journal-entry workaround.

**Re-open surface for already-reconciled lines** (17.0.8.6.0). Each
auto-spawned bridging move carries a `bank_rec_source_line_id` back
to the bank line that triggered it. When the widget opens on a
bank line that has been reconciled before (direct partial OR via a
bridge), `reconciled_aml_ids` is computed from those two sources and
`state` flips to `reconciled`. In that mode the unified top table
renders the bank line and each prior counterpart with a green check
icon, the "Reconciled" banner replaces the in-progress one, and the
**Validate**/**Reset** buttons hide. To re-match against different
counterparts the user reverses the bridging journal entry from the
Journal Entries view, which clears the back-reference and lets the
widget re-open in editable state.

**Kanban + list "Reconciled" surface** (17.0.8.7.0).
`jito.ledger.move.line.bank_rec_done` is a computed boolean that
returns `True` when the line is either directly reconciled
(`reconciled=True`) *or* at least one `jito.ledger.move` carries a
`bank_rec_source_line_id` equal to it. It powers:

* the green check icon + left border on the bank-rec kanban card
  (`view_jito_ledger_move_line_bank_rec_kanban`),
* the **Reconciled** column on the Journal Items list view, and
* the **Reconciled** / **Unreconciled (Open)** search filters.

The earlier `reconciled` Boolean stays on the line — it tracks the
strict residual=0 invariant — but is hidden by default on the list
in favor of `bank_rec_done`, which is the user-meaningful flag for
post-bridging settlement.

**Right-pane refresh on bank-line switch** (17.0.8.7.0). The
two-pane reconciliation view mounts the widget form via
`<View t-key="widgetState.widgetId" ...>` in `kanban.xml`. Without
the `t-key`, OWL keeps the same `View` instance when only the
`resId` prop changes, and the embedded form's internal model
clings to the previous record's data — the user sees the *first*
clicked line forever. Forcing a re-mount via `t-key` guarantees the
right pane reloads on every card click.

**Reset Reconciliation** (17.0.8.8.0). When the widget is in
`state=reconciled`, the toolbar surfaces an orange **Reset
Reconciliation** button (`action_reset_reconciliation`). The handler
unlinks every partial on the bank line and on each bridging move
whose `bank_rec_source_line_id` points here, then resets the bridge
to draft and deletes it. Because the bridges are auto-spawned and
owned by the widget flow, dropping them keeps the books balanced —
no reversal counter-entry is needed. After reset, the originals are
"open" again and the user can re-match. The action returns a
client-reload action so the kanban + form re-render.

**Account balance header** (17.0.8.8.0). The bank-rec kanban left
pane is now a flex column: a sticky header on top shows the bank
account's display name, total balance (formatted via
`tools.misc.formatLang`), and `open / total` line counts. The header
data is fetched once via
`jito.ledger.move.line.get_bank_rec_account_summary(journal_id)` in
the kanban controller's `onWillStart` hook, keyed off
`context.default_journal_id` set by
`jito_ledger_journal.action_open_reconcile_wizard_for_journal`. The
summary is refreshed on `onWidgetSaved` so counts stay in sync with
the user's progress.

**Unified table widget.** The Stock-parity row layout
(liquidity + picks + suspense) is rendered by the OWL widget
`jito_bank_rec_lines_table` (see `lines_table.js` + `lines_table.xml`).
It reads `display_lines_data` — a computed JSON payload on the
widget — so the row composition lives in Python and the front-end is
pure presentation.

### Source Document Attachment (17.0.8.4.0)

`jito.ledger.move` carries a first-class `source_document` Binary
field (with `attachment=True` — bytes offload to `ir.attachment`
filestore) plus a companion `source_document_filename` Char. The
field is surfaced with a different label on each form:

* Customers → Invoices (`view_jito_ledger_move_form_customer_invoice`)
  → label **Invoice PDF** (the document we issued to the customer).
* Vendors → Bills (`view_jito_ledger_move_form_vendor_bill`)
  → label **Vendor Bill Document** (the PDF/DOCX the vendor sent,
  typically containing crypto-pay details).
* Credit Notes / Vendor Refunds (`view_jito_ledger_move_form_invoice`)
  → label **Source Document**, gated `invisible="move_type == 'entry'"`
  so plain journal entries don't expose the slot.

The default `widget="binary"` accepts both PDF and DOCX (Odoo infers
the MIME from filename on download). Editable while the move is
draft; locked once posted (mirrors the existing field-readonly
pattern on this form).

---

## Analytic Accounting (17.0.9.0.0)

Stock-Odoo-style analytic accounting for the Management Ledger, built as
a **fully parallel** dimension that never touches stock `account.move*`
or stock `account.analytic.*`.

### Models (all in `models/`, prefix `jito.ledger.analytic.*`)
- **`jito.analytic.mixin`** — fork of stock `analytic.mixin`; provides
  the `analytic_distribution` JSON field (`{account_id_csv: pct}`),
  search, GIN index, `_validate_distribution`. Retargeted at the ML
  analytic models. Inherited by `jito.ledger.move.line` and
  `jito.ledger.statutory.analytic`.
- **`jito.ledger.analytic.plan`** — hierarchical (`_parent_store`);
  `default_applicability` (optional/mandatory/unavailable);
  `get_relevant_plans()` feeds the OWL widget.
- **`jito.ledger.analytic.account`** — hierarchical; `[code] name`
  display; unique `(code, plan, company)`.
- **`jito.ledger.analytic.distribution.model`** — partner/category/company
  prefill rules (`_get_distribution`).
- **`jito.ledger.analytic.line`** — generated on post for reporting;
  amount in the **line's transaction currency** (separate from the
  17.0.10.0.0 ADR change on `jito.ledger.move.line`, which still
  applies only to the journal-item model). Separate from stock
  `account.analytic.line`.
- **`jito.ledger.statutory.analytic`** — side-table keyed 1:1 by
  `account.move.line` id, holding analytic for the FAAP statutory
  projection. Never writes to stock.

### Generation
`jito.ledger.move._create_analytic_lines()` runs at the end of
`action_post` (and for the reversal counter-move). Per line, per
`{accounts: pct}`, creates one `jito.ledger.analytic.line` with
`amount = -line.amount_currency * pct/100` (stock sign convention).
Idempotent — drops the move's analytic lines first; `action_draft`
deletes them.

### Statutory projection editing
`jito.ledger.statutory.view` (read-only SQL view) LEFT JOINs the
side-table to surface `analytic_distribution` read-only. The form's
**Set Analytic** button (`action_edit_analytic`) find-or-creates the
`jito.ledger.statutory.analytic` row (keyed by the stock line id) and
opens it in a dialog with the editable widget. A SQL view is not
writable, so editing always goes through this explicit find-or-create.

### Widget + picker
`jito_analytic_distribution` (in
`static/src/components/analytic_distribution/`) is a fork of stock's
`analytic_distribution` OWL widget with the 5 model references swapped
to the ML models. Registered for field type `json`. The per-plan
columns are synthesised in-memory by `recordProps` (no server-side
dynamic columns needed). It opens an inline dropdown on click in
editable contexts; in read-only lists it just displays the tags.

**Grid dialog** (17.0.9.0.4) — because the inline dropdown is easy to
miss and inert in read-only lists, every analytic column carries a
**pie-chart button** that opens the OWL grid dialog
`JitoAnalyticDistributionDialog`
(`static/src/components/analytic_distribution/jito_analytic_distribution_dialog.js`).
The dialog is the stock-style grid:
- one column per Analytic Plan (account selector per plan),
- a **Percentage** column and a **Subtotal** column with two-way
  recompute (editing one recalculates the other against the line
  amount; the Subtotal column hides when the target has no amount, e.g.
  distribution models),
- per-plan header total, e.g. `Cost Center (82.5%)`,
- add / remove lines, and hide / unhide plan columns (checkboxes).

It's wired as a **client action** `jito_open_analytic_dialog`: the
server buttons return `{'type':'ir.actions.client','tag':
'jito_open_analytic_dialog','params':{res_model,res_id,amount,
currency_id}}`; the registered handler opens the dialog and, on Save,
writes the recomposed `{account_ids_csv: pct}` JSON to the target via
ORM (regenerating analytic lines for posted move lines) then
`soft_reload`s the view. Entry points:
- `jito.ledger.move.line.action_open_analytic_picker` — buttons on the
  JE line editor, invoice/bill line editors, and Journal Items list/form.
- `jito.ledger.statutory.view.action_edit_analytic` — find-or-creates
  the `jito.ledger.statutory.analytic` side row, then opens the dialog
  on it (statutory tree button + form **Set Analytic** header button).

(The earlier `jito.ledger.analytic.picker` server wizard from 17.0.9.0.3
is removed — a server tree can't render dynamic per-plan columns.)

### Config + gating
Configuration → **Analytic Accounting** subsection (Distribution Models
/ Accounts / Plans) + **Analytic Items** under Accounting → Journals.
All gated by `group_mgmt_ledger_analytic` (security/groups.xml), granted
via the **Analytic Accounting** toggle in Management Ledger Settings
(`res.config.settings.group_jito_ledger_analytic`,
`implied_group='jito_ledger_nl.group_mgmt_ledger_analytic'`). Mirrors
stock's `group_analytic_accounting` pattern.

**Enabled by default** (17.0.9.0.1): `base.group_user` implies the
analytic group out of the box. Fresh installs get it via the
`noupdate="1"` record in `security/groups.xml`; existing installs get it
via `migrations/17.0.9.0.1/post-migrate.py` (one-time grant). Because
both are one-shot, a user who later un-checks the toggle keeps it off
across future upgrades.

### Editing analytic on posted entries (17.0.9.0.2)
Analytic distribution is a non-financial management dimension, so it
stays editable **after posting** (stock Odoo behaves the same):
- **Journal Entries form** — the line editor unlocks only the
  `analytic_distribution` column on posted moves; account / partner /
  label / currency / debit / credit are locked (`readonly="parent.state
  != 'draft'"`). The list is fully locked only on `reversed` moves. New
  rows are effectively blocked (the required `account_id` is readonly),
  and the per-currency balance constraint still guards integrity.
- **Journal Items form** — editable with every field readonly **except**
  `analytic_distribution`; the uniform place to reclassify analytic on
  any line (including posted invoice/bill lines, whose inline editors
  remain draft-only).

`jito.ledger.move.line.write` detects an `analytic_distribution` change
on a posted line and re-runs `move._create_analytic_lines()` for the
affected posted moves, so the generated `jito.ledger.analytic.line`
rows never go stale (mirrors stock's `_inverse_analytic_distribution`).

Note: no fiscal/period-lock guard is applied to analytic edits — by
design, since analytic is a management dimension independent of the
financial close. Add a `move._check_fiscalyear_lock_date()` call in the
write hook if stricter audit behavior is wanted.

### Analytic Reporting menu (17.0.9.0.5)
**Management Ledger → Reporting → Analytic Reporting**
(`action_jito_ledger_analytic_reporting`) is the multi-view reporting
surface over `jito.ledger.analytic.line`. It opens on **Pivot** by
default and offers **list / kanban / graph / grid**
(`view_mode="pivot,tree,kanban,graph,grid"`). The **grid** view (account
rows × date month/year columns, amount measure) requires the Enterprise
`web_grid` module, now a `depends` of `jito_ledger_nl`. The menu item
lives under the **single** "Reporting" section owned by
`jito_ledger_reports` (`menu_jito_ledger_reports_section`), beside Trial
Balance / Partner Ledger — the menuitem
(`menu_jito_ledger_analytic_reporting`) is defined in
`jito_ledger_reports/views/menus.xml` (17.0.4.1.0) because that module
loads after `jito_ledger_nl` and so can reference this module's
`action_jito_ledger_analytic_reporting`; defining a Reporting section
here would duplicate the top-level menu. The item is gated by
`group_mgmt_ledger_analytic`. The older **Accounting → Journals →
Analytic Items** action (`tree,pivot`) is unchanged.

Caveat: pivot/graph/grid sum `amount` in each line's transaction
currency without conversion (same limitation as the base pivot) — group
or filter by currency for cross-currency cleanliness.

### Isolation guarantee
No `account.analytic.line` is ever created from ML activity, and no
analytic is ever written onto `account.move.line`. Stock Accounting's
analytic reports show nothing from the ML.

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
- **Full reconcile groups** (`account.full.reconcile`-equivalent) —
  skipped in v1; `payment_state` derives from the AR/AP line's
  `reconciled` directly. Add if reports need to query "all lines in a
  closed reconciliation graph."
- **Automatic matching by partner+amount+date** — manual only in v1
  (via the reconcile wizard on the Journal Items list).
- **Cross-account same-currency matching** is supported as of
  17.0.8.3.0. Mirrors stock `account.partial.reconcile`: only the
  closure-group model (`account.full.reconcile`, not shipped in v1)
  enforces same account. The residual chain on
  `jito.ledger.move.line` is per-line, so AR ↔ bank/wallet matching
  works out of the box.
- **Cross-currency FX reconciliation** — strict same-currency in v1.
  Cross-currency settlement still requires a manual bridging entry
  that zeros out via a CLR.* account, then reconcile each side
  separately.
- **Destructive reversal** — Phase 4 territory on `jito.mgt.adjustment.je`.
- **Source-line traceability table** (`jito.ledger.trace`) — Phase 4.
- **Per-company sequence numbering** — global sequence in v1.

For the rest of the v1 trajectory, see [`docs/IMPLEMENTATION_PLAN.md`](../../docs/IMPLEMENTATION_PLAN.md).

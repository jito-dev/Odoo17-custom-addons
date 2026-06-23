# jito_ledger_extension — Developer Guidance

## Module Purpose

`jito_ledger_extension` is **Phase 3** of the management-ledger feature
(see [`docs/HLD.md`](../../docs/HLD.md) and
[`docs/IMPLEMENTATION_PLAN.md`](../../docs/IMPLEMENTATION_PLAN.md) §6).

Per HLD Decision #4 + Decision #7, **Extension Ledger entries already
exist as `jito.ledger.move` rows with `entry_type='ext_adjustment'`**
(Phase 2 schema). This module ships:

- **No new tables.**
- **No new ACLs** — uses Phase 2's permissions.
- **No new menu items** — adjustments appear in Phase 2's Journal
  Entries / Journal Items views with the existing entry-type filter.

What it does add: focused UX on the `kind=extension` ledger form so
creating and reviewing extension adjustments is one click rather than
a manual entry-type filter.

---

## Architecture Overview

### What is an Extension Ledger?

Per PRD §Vocabulary, an Extension Ledger is "a lightweight adjustment
ledger built on top of a base ledger. It does not copy the full
accounting data, but adds only its own adjustment or reclassification
entries while reading the original data from the underlying ledger."

In our model:

```
Base Ledger              Extension Ledger
(LL or NL)               (kind=extension)
─────────────────        ──────────────────────
account.move (LL)        jito.ledger.move
   or                       entry_type='ext_adjustment'
jito.ledger.move (NL)       ledger_id=<this extension>
   entry_type='nl_doc'
```

Reporting (Phase 5) presents the **union**: base entries + extension
adjustments. v1 uses on-the-fly aggregation; no materialised SQL view
(per HLD Decision #7).

### Why Phase 3 is small

Everything needed to *create* an extension adjustment was already in
Phase 2. A user can:

1. Create a `kind=extension` ledger (Phase 1 UI).
2. Add a journal to it via Journals tab (Phase 1 UI).
3. Create a journal entry through Phase 2's Journal Entries menu,
   manually setting `entry_type` to "Extension Adjustment".

That works, but the UX is awkward — picking the right entry_type each
time is friction. Phase 3 polishes that.

---

## Main Models

### `jito.ledger` (extended)

**File:** `models/jito_ledger.py`

**No new fields beyond computed counts:**

| Field | Type | Notes |
|---|---|---|
| `extension_adjustment_count` | Integer (computed) | Count of `jito.ledger.move` rows with `entry_type='ext_adjustment'` and `ledger_id` = this. Zero on non-extension ledgers. |
| `base_ledger_entry_count` | Integer (computed) | Count of entries on the base ledger. Reads `account.move` when `base_ledger_id.kind=leading`; reads `jito.ledger.move` when `base_ledger_id.kind=non_leading`. Zero on non-extension ledgers. |

**Three new methods:**

| Method | Returns | Used by |
|---|---|---|
| `action_view_extension_adjustments()` | act_window opening a tree of ext_adjustment moves on this ledger | Adjustments stat button |
| `action_view_base_ledger_entries()` | act_window opening either `account.move` (if base=LL) or `jito.ledger.move` (if base=NL) | Base Entries stat button |
| `action_create_extension_adjustment()` | act_window opening a new `jito.ledger.move` form with `default_ledger_id` and `default_entry_type='ext_adjustment'` | "New Extension Adjustment" header button |

All three raise `UserError` if called on a ledger where `kind != 'extension'`.

---

## Views

### `views/jito_ledger_extension_views.xml`

A single inherited view of `jito_ledger_core.view_jito_ledger_form`:

1. **Header section** added before `<sheet>` containing the
   "New Extension Adjustment" button.
   - `invisible="kind != 'extension' or not id"` — hidden on
     non-extension ledgers and on unsaved (draft) records.
2. **`oe_button_box`** added after the archive ribbon containing two
   stat buttons.
   - "Adjustments" — `invisible="kind != 'extension'"`.
   - "Base Entries" — also hidden when `not base_ledger_id` (extension
     in initial state, no base picked yet).

The form remains identical for `leading` and `non_leading` ledgers —
the new controls only appear on extensions.

---

## Business Logic

### Combined-view reporting (preview)

Phase 3 does not implement reporting. Phase 5's
`jito_ledger_reports` will query both:

```python
# Pseudo-code for a future Management Trial Balance on an extension ledger
def get_combined_lines(extension_ledger):
    base = extension_ledger.base_ledger_id
    if base.kind == 'leading':
        ll_lines = env['account.move.line'].search([
            ('company_id', '=', extension_ledger.company_id.id),
        ])
    else:
        ll_lines = env['jito.ledger.move.line'].search([
            ('ledger_id', '=', base.id),
            ('move_state', '=', 'posted'),
        ])
    ext_lines = env['jito.ledger.move.line'].search([
        ('ledger_id', '=', extension_ledger.id),
        ('entry_type', '=', 'ext_adjustment'),
        ('move_state', '=', 'posted'),
    ])
    return ll_lines + ext_lines
```

The Phase 3 stat buttons preview that idea: they count what the
combined view would aggregate.

### Performance

`extension_adjustment_count` and `base_ledger_entry_count` are
computed via `search_count` on every read. For typical tenants
(few ledgers, modest entry volumes) this is fine. If a tenant has
millions of LL entries and many extension ledgers, these counts may
become a hotspot — switch to a stored compute or read-group at that
point.

---

## Security

**No changes.** Phase 1 and Phase 2 ACLs cover the underlying models:
- `jito.ledger` (Phase 1) — admin full, others read.
- `jito.ledger.move` and `jito.ledger.move.line` (Phase 2) — Accountant
  / Senior / Admin read+write+create+unlink; FM read-only.
- `account.move` (stock Odoo) — standard accounting groups.

The new computed fields and methods inherit these permissions
naturally (a user who can read `jito.ledger` can read its computed
counts; opening the action requires read on the target model).

---

## Integration Guidelines

### For Phase 5 (`jito_ledger_reports`)

Phase 5's report custom handlers will:
- Use `jito.ledger.kind == 'extension'` to detect extension ledgers.
- Walk `base_ledger_id` to get the base.
- Query both base entries and extension adjustments, merge into a
  combined report view.
- Apply FX presentation translation (HLD Decision #1, FR-23) at report
  time, regardless of whether lines come from LL or NL.

### For tenants

After install:
1. Open an existing or create a new ledger with `kind=extension`.
2. Header now shows **New Extension Adjustment** button.
3. Sheet shows two stat buttons: **Adjustments** and **Base Entries**.
4. Click "New Extension Adjustment" to open a pre-filled move form;
   fill in journal, lines, and post.
5. Counts on the stat buttons update on next refresh of the ledger
   form.

---

## Verification Checklist (Phase 3)

After installing the module:

1. **Install completes** without errors. No new menu items.
2. **Open a non-extension ledger** (LL or NL). Form looks unchanged —
   no new buttons, no new sections.
3. **Open or create an extension ledger** (`kind=extension`,
   `base_ledger_id` set):
   - Header shows **"New Extension Adjustment"** button.
   - Sheet shows **two stat buttons** (Adjustments + Base Entries) with
     counts.
4. **Click "New Extension Adjustment"** → new move form opens with
   `Ledger` pre-filled to the extension ledger and `Entry Type` set to
   "Extension Adjustment". Pick a journal, add balanced lines, post.
5. **Reopen the extension ledger.** "Adjustments" count = 1.
6. **Click "Adjustments"** → tree opens filtered to this ledger's
   ext_adjustment moves. The "New" button works (uses the same
   defaults).
7. **Click "Base Entries"** → opens either `account.move` (if base=LL)
   or `jito.ledger.move` (if base=NL), filtered correctly.
8. **Edge case — extension without a base.** If somehow a `kind=extension`
   ledger has `base_ledger_id` empty (Phase 1's `_check_base_ledger`
   should prevent this, but for safety): the "Base Entries" button is
   hidden, the "Adjustments" button still works.
9. **Save a brand-new extension ledger.** Before saving, the header
   button is hidden (`not id`). After saving, it appears.

---

## Out of scope (deferred to Phase 5 / v1.x)

- **Combined-view reports** — Phase 5.
- **Materialised SQL view** — explicitly out per HLD Decision #7.
- **FX translation in extension entries** — Phase 5 (FR-23, applies
  uniformly across LL / NL / extension).
- **Ext-adjustment-specific document types** (sales-style, purchase-style)
  — generic `jito.ledger.move` covers v1.

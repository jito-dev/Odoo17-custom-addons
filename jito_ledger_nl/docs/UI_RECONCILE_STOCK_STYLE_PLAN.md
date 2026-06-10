# Stock-Style Reconciliation UI — Implementation Plan

Target module: `jito_ledger_nl`
Target version: `17.0.8.2.0`

## Goal

Rewrite the right-pane reconciliation form of `jito.bank.rec.widget` so it
mirrors stock Odoo Enterprise's `account_accountant` bank reconciliation
widget, both visually and behaviourally:

1. **Unified top table** — one table that shows the bank/liquidity line,
   every picked counterpart, and the auto-balance/suspense line. Each row
   exposes Account / Partner / Date / Debit / Credit, with a second
   sub-row showing the source-move name and memo.
2. **Notebook tabs** below the table:
   - **Match Existing Entries** — searchable AMLs list; click a row to
     add as a counterpart, click again to remove.
   - **Manual Operations** — placeholder for v1 (we don't ship manual
     adjustments yet; the tab explains the alternative).
   - **Discuss** — source-move details and chatter pointer.
3. **Statusbar buttons** rendered as a left-aligned toolbar: **Validate**
   (primary when balanced) and **Reset** (when picks exist).

## Root cause of the current "click does nothing" bug

`jito_bank_rec_widget_views.xml` declared the AMLs list with
`js_class="jito_bank_rec_amls_list_view"` on the embedded `<tree>` inside
a `<field mode="tree">`. Odoo 17's `X2ManyField` mounts the base
`ListRenderer` directly (see `web/.../x2many_field.xml` line 35) and
never consults `js_class`. Result: `JitoBankRecAmlsRenderer.onCellClicked`
was never invoked. The renderer was registered in the **views** registry
but the X2Many embedding only consults its hard-wired `ListRenderer`
import.

Fix path: keep the custom renderer, but expose it as a **field widget**
(`widget="jito_bank_rec_amls"`) by subclassing `X2ManyField` and
substituting our renderer in its `components` map.

## Files

### New

| Path | Role |
|---|---|
| `static/src/components/bank_reconciliation/lines_table.js` | OWL widget for the unified top table. |
| `static/src/components/bank_reconciliation/lines_table.xml` | Template for the unified table (Stock parity). |

### Modified

| Path | Change |
|---|---|
| `models/jito_bank_rec_widget.py` | Add `suspense_account_id`, `display_line_ids_data` (computed JSON), and helper for line synthesis. Add `action_to_check` placeholder for v1. |
| `static/src/components/bank_reconciliation/amls_list_view.js` | Register `jito_bank_rec_amls` field widget (subclass X2ManyField with custom renderer). Keep existing renderer logic. |
| `static/src/components/bank_reconciliation/kanban.scss` | Stock-parity styles for the unified table, statusbar buttons, notebook layout, selected-row highlight. |
| `views/jito_bank_rec_widget_views.xml` | Restructured form: statusbar buttons, unified-table widget, notebook tabs. `widget="jito_bank_rec_amls"` on the AMLs field. |
| `__manifest__.py` | Bump version, add new JS+XML asset entries. |
| `GUIDANCE.md` | Document the new UI + bug-fix note. |

## Backend additions

- **`suspense_account_id`** (M2O `jito.ledger.account`) — read-only,
  computed from the journal's reconcile-clearing account (default:
  search by account semantic family `clr`). Used for the auto-balance
  row when the picks don't fully cover the bank amount.
- **`display_lines_data`** (Text, computed) — JSON payload of the
  synthesised rows for the OWL widget. Avoids creating a parallel
  transient model for display-only rows.
- **`action_to_check`** — no-op placeholder. Toggling "To Check" is a
  v1.x feature; the button is rendered but disabled until then.

## Click-to-add behaviour

The OWL renderer's `onCellClicked` already calls
`action_add_new_aml` / `action_remove_new_aml`. Once the renderer is
actually wired via the field-widget approach, those RPCs fire on every
row click and the form reloads to surface the new pick in the unified
table.

## Quality / UX / Supportability evaluation

- **Quality**: keeps the backend transient model intact (no schema
  rewrite), avoids the heavyweight pattern Stock uses (custom
  RelationalModel + custom KanbanController override). One small OWL
  widget + a field-widget shim are the only new surface area.
- **UX**: mirrors Stock layout the user already knows.
- **Supportability**: changes are local to `jito_ledger_nl/static/src/`.
  No impact on other modules. The unified-table data is a JSON
  computed field so changes to the row shape don't require migrations.

## Out of scope (deferred to a later patch)

- Multi-line manual operations (Stock's "Manual Operations" tab
  full functionality).
- Reconciliation models / suggestions (top-right toolbar in Stock).
- Inline editing of counterpart amount in the unified table; we keep
  the existing match-amount edit in the picked-counterparts pattern via
  the AMLs RPC (`action_add_new_aml` defaults to full residual).

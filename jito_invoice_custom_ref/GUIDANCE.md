# jito_invoice_custom_ref — Guidance

## What This Module Does

Adds a **lockable custom reference field** (`Custom Invoice Reference`) to customer invoices (`out_invoice`). This is independent of Odoo's built-in invoice sequence (`name` field, e.g. `INV/2024/00042`) and is intended for storing an external system's invoice number in the format `INV-YYYY-N`.

## Main Models

### `account.move` (extended)

| Field | Type | Description |
|---|---|---|
| `custom_invoice_ref` | `Char` | Free-text external reference. `copy=False`, `tracking=True`. |
| `custom_invoice_ref_locked` | `Boolean` | Soft lock flag. When `True`, the ref field becomes read-only. `copy=False`. |

### Methods

- `action_lock_custom_invoice_ref()` — Sets `custom_invoice_ref_locked = True`.
- `action_unlock_custom_invoice_ref()` — Sets `custom_invoice_ref_locked = False`.

## Views

`views/account_move_views.xml` inherits `account.view_move_form` with two XPath injections:

1. **Header buttons** (before status bar):
   - **Lock Custom Ref** — visible when `move_type == 'out_invoice'`, field has a value, and is not yet locked.
   - **Unlock Custom Ref** — visible when locked.

2. **Custom ref field** — inserted after the `h1` invoice number inside `.oe_title`:
   - Shows a "Locked" badge when locked.
   - Entire block invisible for non-customer-invoice move types.

## Business Logic & Constraints

- **Soft lock only**: The lock prevents accidental edits in the UI. Any user with write access to `account.move` can unlock.
- **No sequence**: The field is plain `Char` — no auto-numbering, purely manual.
- **Audit trail**: `tracking=True` logs all changes to `custom_invoice_ref` in the chatter.
- **No ACL needed**: Extends `account.move`; existing access rights apply.

## Invoice PDF Override

`views/report_invoice.xml` inherits `account.report_invoice_document` and replaces the `<p name="payment_communication">` paragraph. When `custom_invoice_ref` is set, it is used as the displayed reference; otherwise Odoo's default `payment_reference` (the internal sequence number) is shown as a fallback.

## Important Patterns

- Visible **only on `out_invoice`** — hidden on vendor bills, credit notes, journal entries.
- `copy=False` on both fields — duplicating an invoice does not copy the reference.
- Works in both `draft` and `posted` invoice states.

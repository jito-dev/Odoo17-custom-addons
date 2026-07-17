# Match & Attach Vendor Bills (Revolut tx ↔ existing Odoo bill)

Link an **existing** Odoo vendor bill (`account.move`, `in_invoice`) to the Revolut transaction that paid it, so
reconciliation rides the existing machinery. Generic — matches **any** Accounting vendor bill (no dependency on the
contractor-payroll module).

## Why
A Revolut transaction has richer data than its injected statement line — the transfer label ("To PE NAME"), amount,
and the **payment‑reference UID**. Matching the bill to the *tx* (then letting injection reconcile) is more reliable
than reconciling against the terse bank line.

## Flow
1. **Revolut Transactions** list → select → ⚙ Actions → **Match & Attach Vendor Bills**
   (`ir.actions.server` → `revolut.transaction.action_open_bill_link_wizard`).
2. The wizard proposes a bill per tx (`_find_matching_bill`): **reference (UID) + amount** first (UID is unique →
   near‑certain), else **partner name + amount + date**. Review/override the **Vendor Bill**, tick **Attach**.
3. **Attach** sets `revolut.transaction.vendor_bill_id` (a *reference/link*, not a copy). If the tx is already
   injected and the bill is **posted**, it reconciles immediately (`_auto_reconcile_bill`).

## Reconciliation (reused, no new logic)
- **At injection:** `action_inject_to_accounting` auto-reconciles a **posted** `vendor_bill_id` (existing hook).
- **Already injected:** the wizard reconciles on attach; or use the existing **Reconcile Bills** action
  (`action_reconcile_vendor_bill`). Draft bills aren't reconciled — post them first (e.g. payroll's *Confirm Vendor
  Bill*).

## Matching rules (`models/revolut_bill_creation.py:_find_matching_bill`)
- Candidates: `in_invoice`, same company, `payment_state in (not_paid, partial)`, **not already linked** to another
  tx, `amount_total` within 1% / 2¢ of `abs(amount)` (or `bill_amount`).
- **High:** the bill `ref` (UID) appears in the tx `reference`/`description`, amount matches.
- **Medium/Low:** partner-name tokens in the tx description/merchant, amount matches, `invoice_date` within ±14d.
- No match → line shown with "No match"; pick a bill manually in the review row.

## Key files
- `models/revolut_bill_creation.py` — `_find_matching_bill`, `action_open_bill_link_wizard`; reuses `vendor_bill_id`
  + `_auto_reconcile_bill`.
- `wizards/revolut_bill_link_wizard.py` / `revolut_bill_link_line.py` — the review wizard.
- `views/revolut_bill_link_wizard_views.xml` — review tree + the list-bound server action.

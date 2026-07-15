# Revolut → Accounting pipeline (bank tx → bill → reconcile)

Expenses must be backed by a **bill** — the bank line never books an expense directly. The flow is a reversible
3-step pipeline, surfaced by the **`accounting_stage`** field (statusbar on the form, badge column + filters on the list).

## Stages (`accounting_stage`, computed)
`to_inject` → `needs_bill` → `bill_draft` → `to_reconcile` → `reconciled`. Internal lines (transfers/FCF) go
`to_inject` → `injected` (no bill needed).

## Step 1 — Inject Bank Txs  (`action_inject_to_accounting`)
Creates `account.bank.statement.line`s. **Internal transfers** → company transfer account; **FCF** lines → their
per-account FCF accounts; **Revolut fees** (`fee` type, split into their own tx) → **Bank Charges** directly
(`_bank_charges_account`; configurable via *Revolut Bank Charges*, else auto-created — no bill, terminal stage
`injected`); **everything else** → the journal **suspense** (no expense routing, no analytic). Reverse:
**Remove Bank Txs** (`action_remove_from_accounting`).

## Step 2 — get a bill
- **Inject attached Bill** (`action_create_vendor_bill`): for a tx with a **receipt** (Gmail/Revolut/manual upload)
  and no bill yet → creates a **draft** vendor bill. AI fills vendor/amount/date; the **expense line account** comes
  from the **Injection Rules** (merchant→6xxx) and is tagged with the **Data Source: Revolut Business API** analytic.
  Reverse: **Remove attached Bill** (`action_remove_attached_bill`) — deletes only Revolut-created bills.
  - **Amount comes from the transaction, not the AI** (`_apply_tx_amount`): AI line breakdowns/totals are
    unreliable, so every injected bill is rewritten to a **single gross line (no tax)** using the tx's **original
    amount & currency** (`bill_amount`/`bill_currency`, e.g. 100 USD), falling back to the settled `amount`/`currency`.
    What the card was actually charged is the company's expense — split checks self-resolve (the card is only charged
    the payer's share). A chatter note records the AI-detected total for audit. When the original currency differs
    from the bank line's currency, **reconciliation books the difference as a standard FX gain/loss** (Odoo's
    cross-currency reconciliation; no manual step).
  - **Multicurrency bank line** (`action_inject_to_accounting`): when the original (merchant) currency differs from
    the journal currency — e.g. a **EUR invoice paid from a USD account** — the statement line is injected as
    multicurrency: `amount` = the actual USD cash, `foreign_currency_id` = EUR, `amount_currency` = the original EUR
    amount. This lets the EUR bill reconcile **1:1 in EUR** so Odoo posts the USD rate gap to the configured
    **Foreign Exchange Gain/Loss** account automatically. Without this, the bank line is pure USD and Odoo sees only an
    unexplained residual (no clean FX). Re-inject any tx injected before this fix (Remove from Accounting → Inject).
- **Match & Attach Vendor Bills** (wizard): link a **pre-existing** Accounting bill (link only). Reverse:
  **Unlink Vendor Bill** (`action_unlink_vendor_bill`) — keeps the bill.

## Step 3 — Reconcile injected bill & tx  (`action_reconcile_vendor_bill`)
Posts the draft bill and reconciles the bank line ↔ the bill's payable (`_auto_reconcile_bill`, `bank.rec.widget`).
Now the expense lives on the **bill**, backed by a document; the bank line clears AP. Reverse:
**Unreconcile injected bill & tx** (`action_unreconcile_bill`) — removes the match, keeps the link/bill.
Robustness (cross-currency safety): before matching, `_auto_reconcile_bill` (a) **self-heals** a stale/partial
bill-payable reconciliation left by an earlier failed attempt, (b) **aligns the bank line to the bill's currency**
(`_align_bank_line_to_bill_currency` — sets `foreign_currency_id`/`amount_currency` to the bill's exact amount so a
foreign bill reconciles 1:1 and the rate gap posts to FX gain/loss; repairs old pure-journal-currency lines without
re-inject; the bank `amount`/actual cash is never changed), and (c) runs inside a **savepoint** so a mid-way failure
rolls back fully instead of leaving the payable half-reconciled.

## Where the expense + analytic live now
On the **bill's** expense line (Injection-Rule account + Data Source analytic) — **not** on the bank statement line.
The Injection Rules and `_ensure_data_source_analytic` are reused at bill-creation time
(`_create_vendor_bill_from_attachment`).

## Reconcile transfers & fees  (`action_reconcile_transfers_fees`)
The non-bill finalizer (parallel to "Reconcile injected bill & tx", which is bill-only). An internal transfer is one
`revolut_id` split into two rows (one per `account_revolut_id`), each posting to the company **Transfer (clearing)
account**. This action **reconciles each transfer's two Transfer-account legs against each other** (`_reconcile_transfer_legs`)
so the clearing account nets to zero — making the account `reconcile`-able if needed. For **fees** it confirms they're
booked to **Bank Charges** (already done at inject since v1.92.0) and **re-injects** any legacy fee that fell to
suspense. Fees/transfers never need a vendor bill, so they don't pass through the bill pipeline.

## Full teardown — Remove from Accounting  (`action_remove_all_from_accounting`)
One-click reverse of the **whole** pipeline for a tx: unreconcile → delete the Revolut-**created** bill (or unlink a
**pre-existing** attached bill, keeping it) → delete the injected bank statement line. Leaves the tx back at
`to_inject`. Pre-existing attached bills are never deleted (they exist independently) — only unlinked. Available as a
confirm-guarded form button and the **Remove from Accounting (full)** list action.

## Actions inventory (⚙ on the tx list, numbered for order)
1. Inject Bank Txs · Remove Bank Txs · 2. Inject attached Bill · Remove attached Bill ·
3. Reconcile injected bill & tx · Unreconcile injected bill & tx · Match & Attach Vendor Bills · Unlink Vendor Bill ·
**Remove from Accounting (full)** — nukes tx+bill+reconciliation in one step.

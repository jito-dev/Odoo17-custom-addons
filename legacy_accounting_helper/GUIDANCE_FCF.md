# FCF (Revolut money-market-fund) accounting

How Revolut **FCF** (Flexible Cash Funds) transactions are classified and posted when injected.

## Flow
FCF rows are imported (`fcf.csv.import.wizard`) into `revolut.transaction` with coarse types
`fcf_buy / fcf_sell / fcf_interest / fcf_fee`, then injected as `account.bank.statement.line` by
`revolut.transaction.action_inject_to_accounting`. The injector sets each line's `counterpart_account_id` so it
posts straight to the right account (gl-style, no document).

## Classification (`revolut.transaction._fcf_counterpart_account`)
The importer collapses the three interest variants into one `fcf_interest` type, so the classifier matches on the
**description** label:

| FCF line | counterpart | P&L? |
|---|---|---|
| **BUY / SELL** (`transfer_between_accounts`) | company **transfer account** (`res.company.transfer_account_id`) | no — internal transfer, reconciles vs the main bank's "Internal transfer to/from fund" lines |
| **Service Fee Charged** (`fcf_fee`) | **FCF Service Fees** (expense) | yes |
| **Interest PAID** (`fcf_interest`, label starts "Interest PAID") | **FCF Interest Income** (income) | yes — the real interest earned |
| **Interest Reinvested / WITHDRAWN** (`fcf_interest`, other labels) | **FCF Internal Suspense** (asset) | no — Revolut-internal moves, parked, never silently income |

Per-currency **holding** = each `save.usd`/`save.eur` bank journal's own default account (`asset_cash`, e.g. 101414 /
101413). The three accounts above are **shared** across currencies (currency is on each move line, so reports can
still split USD vs EUR).

## Why "PAID only" for income
The interest lines have mixed signs — PAID (+), Reinvested (−), Withdrawn (−). Booking all of them as income would
**understate** the true interest (net ≈ €941 vs real €4,148). So only **Interest PAID** → income; Reinvested /
Withdrawn → Suspense (they're moving already-earned interest, not new income). The Suspense balance ties out against
the income recognised at PAID.

## Configuration — per account
FCF posting accounts are configured **per Revolut account** on `revolut.account.journal.map` (no shared default):
- Tick **FCF Account** (`is_fcf`) on the account — visible as a column in **Configuration → Revolut Account
  Mappings** (and in the **Flexible Cash Funds** list) so you can see at a glance which accounts are FCF.
- On the account form (both the standard mapping form and the **Flexible Cash Fund Account** form), once FCF is
  ticked, set its three posting accounts: **Interest Income (PAID)**, **Service Fees**, **Internal Suspense
  (Reinvested/Withdrawn)** (`fcf_interest_income_account_id` / `fcf_service_fee_account_id` /
  `fcf_suspense_account_id`).
- `_fcf_counterpart_account(mapping)` reads these per-account and only fires when `mapping.is_fcf`; if a field is
  left empty that line falls to the journal's suspense (never silently booked as income).

Old/Hedging/UUID funds are wired the same way (tick FCF + set accounts). Create the GL accounts yourself in the
Chart of Accounts (suggested: Interest Income = income/other-income, Service Fees = expense, Internal Suspense =
current asset).

## Key code
- `models/revolut_account_journal_map.py` — `is_fcf` + the 3 per-account fields.
- `models/revolut_transaction.py` — `_fcf_counterpart_account(mapping)` + the hook in `action_inject_to_accounting`.
- `views/revolut_account_map_views.xml` — `is_fcf` column on both lists; FCF Posting Accounts group on both forms.

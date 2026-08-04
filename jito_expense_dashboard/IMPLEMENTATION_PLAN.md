# Implementation plan — Expenses dashboard fed from accounting

Date: 2026-07-31

## Problem

`Dashboards → Finance → Expenses` shows no figures, while `Accounting` and `Invoicing`
on the same screen show live data.

## Diagnosis

Not a code defect. Checked on `odoo_dev` (prod copy, data current to 2026-07-28):

- `spreadsheet.dashboard` id=10 "Expenses" exists in the Finance group, sequence 40
- its spreadsheet attachment is intact (46 056 bytes, byte-identical to the module's
  source JSON)
- `hr_expense`, `sale_expense`, `spreadsheet_dashboard_hr_expense` all `installed`
- every field the dashboard references exists on the Odoo 17 `hr.expense` model

The cause is data, not code:

```
hr_expense        0 records
hr_expense_sheet  0 records
```

All six pivots and the list on that dashboard read only from `hr.expense`. Costs are
booked as vendor bills and journal entries instead: 497 `in_invoice`, 1395 `entry`, and
807 posted journal items on expense-type accounts.

## Options considered

1. **Custom dashboard over accounting data** — shows the real money immediately, no
   process change. *Chosen.*
2. Start using the Expenses app — fills the stock dashboard, but only ever covers
   employee-reimbursed spend, not vendor bills.
3. Hide the empty dashboard — cosmetic only, delivers no figures.

## Design

New module `jito_expense_dashboard` (17.0.1.0.0), depends on `account` and
`spreadsheet_dashboard`. Ships one `spreadsheet.dashboard` record plus its o-spreadsheet
JSON; no Python models, no view overrides, nothing touched outside `jito_modules/`.

Source: `account.move.line`, domain
`account_id.account_type in ('expense','expense_direct_cost')` and
`parent_state = 'posted'`, measure `balance`. Rationale for each choice is recorded in
`GUIDE.md`.

Layout: 4 KPI scorecards, a monthly bar chart, Top Vendors and Top Expense Accounts
tables (top 10 each), and a recent-lines list, all driven by a relative `Period` global
filter defaulting to the trailing 12 months.

Format follows the two working precedents in this codebase — the stock
`spreadsheet_dashboard_hr_expense` and the in-house `jito_ecb_exchange_rate` — using
`version: 12` / `odooVersion: 4` and the `ODOO.PIVOT` / `ODOO.PIVOT.HEADER` / `ODOO.LIST`
positional idioms.

## Verification performed

- `-i jito_expense_dashboard --stop-after-init` on `odoo_dev`: installed clean, no errors
- record lands in Finance at sequence 45, attachment written (23 943 bytes)
- `get_readonly_dashboard()` returns 5 pivots, 1 list, 5 figures, Period filter present
- every block returns non-empty data server-side (totals, vendors, accounts, months,
  recent lines) — figures in `GUIDE.md`
- an `account.group_account_invoice` user sees the new dashboard in Finance

Not performed: browser screenshot of the rendered dashboard — browser tooling was not
available in the session. Visual confirmation is left to the user.

---

# Iteration 2 — financial-reporting polish (v17.0.2.0.0, 2026-07-31)

## Scope

Seven changes, all inside `tools/gen_dashboard.py`; no new models or dependencies.

1. **Prior-period comparison** on the four money/volume KPIs. Pivots 6–8 duplicate the
   current-period pivots and are registered with `offset: -1` in the global filter;
   scorecards gain a `baseline` cell. Verified against
   `spreadsheet/static/src/global_filters/helpers.js:147` — for a relative range the
   offset shifts the window by `365 * offset` days, so the baseline follows whatever
   range the user picks.
2. **"In Draft" KPI** (pivot 9, `parent_state = 'draft'`) — surfaces expense lines that
   the posted-only base domain excludes.
3. **Others and Total rows plus a share-of-total column** in both ranking tables.
4. **`IFERROR` on every data formula** so an empty period renders blank, not `#ERROR`.
5. **Monthly chart stacked by `account_root_id`.** Checked first: `account_root_id` is
   `store=True` and groupable; `account_type` is not and raises *Cannot convert field
   account.move.line.account_type to SQL*. The stack therefore groups by account-code
   root and does not separate direct from operating costs — documented in `GUIDE.md`.
6. **Noise handling.** KPIs stay a literal ledger cut so they reconcile with accounting;
   only the list narrows to `journal_id.type = 'purchase'` and is renamed "Recent Vendor
   Bills", with a footnote explaining the difference in scope. Count KPI renamed
   "Documents" (verified: 801 lines across 801 distinct moves).
7. **Formatting** — company-currency format `[$$]#,##0.00`, `0.0%` for the share column,
   and a `CellIsRule` conditional format painting negative amounts red.

Period default stays `last_year` rather than the fiscal year: the offset comparison is
cleanest on relative ranges, and a fiscal-year default would render a near-empty
dashboard each January.

## Verification performed

`-u jito_expense_dashboard` on `odoo_dev`: clean, no errors. Payload re-checked —
9 pivots, 1 list, 6 figures, 1 conditional format, offsets `{1,2,3,4,5,9: 0; 6,7,8: -1}`.

Server-side figures for the default range (2025-08-01 → 2026-07-31):

```
Total Expenses  251 370.21   (801 documents)   Direct 133 785.75   Operating 117 584.46
In Draft         19 800.00   (1 line)
Top-10 vendors  174 633.85   -> Others 76 736.36 (30.5%)
chart            47 month x account-root buckets
list scope      495 purchase-journal lines of 801
```

**Finding to flag:** the previous window (2024-08-01 → 2025-07-31) holds only 450.00
across 1 document — bookkeeping in this database effectively starts November 2025. The
deltas are therefore not informative on the trailing-12-month range until ~November 2026,
though they work correctly on shorter ranges. Left in place as designed; no code change.

Browser screenshot again not possible in-session; visual confirmation left to the user.

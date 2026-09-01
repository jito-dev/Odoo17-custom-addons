# jito_expense_dashboard

## What this module does

Adds a spreadsheet dashboard **"Expenses (Accounting)"** under **Dashboards → Finance**
that reports real expense spend from accounting entries, laid out as an executive
overview: *how much · trending which way · where it goes · who we pay · what needs
attention*.

It also adds **`jito.expense.category`** — a management categorisation of expense
accounts — because Odoo has no usable dimension for this (see below).

### Why it exists

The stock Odoo dashboard `spreadsheet_dashboard_hr_expense` ("Expenses", sequence 40)
reads **exclusively** from `hr.expense`. Companies that book costs as vendor bills and
journal entries rather than employee expense reports have zero `hr.expense` records, so
every pivot on that dashboard resolves to empty — the dashboard is not broken, it simply
has no source data. This module provides the equivalent view over the data that does
exist.

## Data model

Everything reads from **`account.move.line`** with this base domain:

```python
[('account_id.account_type', 'in', ['expense', 'expense_direct_cost']),
 ('parent_state', '=', 'posted')]
```

Three deliberate choices:

- **`account_id.account_type`, not `account_type`.** `account.move.line.account_type` is
  a *related, non-stored* field. Traversing through `account_id` keeps the domain a plain
  stored-column filter. (The same field is unusable as a groupby — see below.)
- **`parent_state = 'posted'`.** Stored related field on `move_id.state`, so draft and
  cancelled entries are excluded cheaply. What is excluded is surfaced by the "In draft"
  KPI rather than silently dropped.
- **Measure `balance`** — a stored Monetary field already expressed in company currency,
  so no FX conversion happens in the dashboard. Expense lines are debit-positive; refunds
  carry a negative balance and net off correctly.

## Expense categories — why a custom dimension exists

The dashboard needs a readable dimension to stack the trend by. Neither Odoo dimension works:

| Candidate | Why it fails |
|---|---|
| `account_root_id` | `account.root` is an SQL **view** whose `name` is `LEFT(code, 2)`. It can only ever render `60`, `61`, … There is no record to rename and no name field to translate. Worse, root `60` carries **89.7%** of spend and mixes subcontractor work, Upwork/Revolut fees and the catch-all account into one series. |
| `account_type` | Related **without** `store=True` → `Cannot convert field account.move.line.account_type to SQL`. Same for `account_internal_group`. |
| `account.group` | Optional and, in this database, populated for **5 of 31** expense accounts (one group, "Software & Subscriptions"). It also cannot separate the catch-all from subcontractor spend, since both are root 60. |
| `product_id` | **0%** fill rate on expense lines here. |

So the module adds:

```
jito.expense.category          name, code, sequence, colour, note, account_ids
account.account
  .expense_category_id         Many2one, auto-filled from the account code
account.move.line
  .expense_category_id         related=account_id.expense_category_id, store=True  <- groupable
```

Nine categories ship as `noupdate="1"` data: **Subcontractor · Uncategorized ·
SaaS & tools · Platform fees · Professional services · Meals & entertainment ·
Office + FX · Bank & fees · Other**.

### Assignment rules

`models/account_account.py` holds `CODE_PREFIX_MAP`, applied **longest prefix wins**:

- `6000` → Subcontractor, but `600000` → **Uncategorized** (the catch-all beats the
  shorter prefix), and `6005` / `6011` → Platform fees. All three live under root 60 —
  that overlap is the whole point.
- `61` → SaaS & tools, but `611000` (Purchase of Equipments) → Office + FX.
- `6300` → Meals, but `630000` (Salary Expenses) → Other. Same shape for `6200`/`620000`.

Anything the map does not cover falls back to **Uncategorized** — never dropped, never
hidden. Assignment runs from `create()`, from `write()` when `code` or `account_type`
changes, from the `post_init_hook` on install, and from
`migrations/17.0.3.0.1/post-migrate.py` on upgrade.

> `post_init_hook` fires **only on a fresh install** (`odoo/modules/loading.py` checks
> `new_install`). An existing installation is backfilled by the migration script — that is
> why both exist.

**Manual overrides survive.** The automation only fills blanks; it never overwrites a
category someone set by hand. Accountants edit categories at
**Accounting → Configuration → Accounting → Expense Categories**, and set them per account
on the account form (the field is hidden for non-expense account types).

## Dashboard contents

| Block | Kind | Source |
|---|---|---|
| Total expenses | scorecard + delta | pivots 1 / 6 |
| Direct costs | scorecard + delta | pivots 2 / 7 (`expense_direct_cost`) |
| Operating | scorecard + delta | pivots 3 / 8 (`expense`) |
| Documents | scorecard + delta | pivots 1 / 6, `__count` |
| In draft | scorecard | pivot 9, `parent_state = 'draft'` |
| Monthly trend by category | `odoo_bar`, stacked | live query, `date:month` × `expense_category_id` |
| Monthly trend by category | `ODOO.PIVOT` matrix | pivot 12, rows `expense_category_id` × cols `date:month` |
| Expense structure | `odoo_pie` + `ODOO.PIVOT` table | pivot 5, `expense_category_id`, 9 rows + Others + Total |
| Top vendors | `ODOO.PIVOT` table | pivot 4, `partner_id`, top 10 + Others + Total |
| Top expense accounts | `ODOO.PIVOT` table | pivot 13, `account_id`, top 10 + Others + Total |
| Recent vendor bills | `ODOO.LIST` table | list 1, purchase journals only |
| Needs attention | cell block | pivots 10 (uncategorised), 11 (root-60 share), 9 (drafts) |

A global filter **Period** (relative date, default `last_year` = rolling 365 days) is
wired to the `date` field of all eleven pivots, the list and both charts.

### Prior-period comparison

Pivots 6, 7 and 8 duplicate the three money KPIs but are registered in the global filter
with **`offset: -1`**. For a relative range, `getRelativeDateDomain`
(`spreadsheet/static/src/global_filters/helpers.js`) shifts the window by
`365 * offset` days for `last_year`, and by the corresponding span for the shorter
ranges. So the baseline always tracks whatever range the user selects — pick "Last 30
Days" and the delta compares against the 30 days before.

Scorecards read `Data!B*` as the value and `Data!C*` as the `baseline`, with
`baselineMode: "difference"`. Colours are inverted on purpose
(`baselineColorUp` red, `baselineColorDown` green): spending *more* than the previous
period is the bad direction.

## Files

```
models/expense_category.py                     jito.expense.category
models/account_account.py                      CODE_PREFIX_MAP + auto-assignment
models/account_move_line.py                    stored related -> groupable
hooks.py                                       post_init_hook (fresh install)
migrations/17.0.3.0.1/post-migrate.py          backfill on upgrade
data/expense_category_data.xml                 the nine categories (noupdate)
views/expense_category_views.xml               config menu + tree/form
views/account_account_views.xml                field on account form/list/search
data/expense_dashboard.xml                     spreadsheet.dashboard record + hides the stock one
tests/test_dashboard_visibility.py             which Expenses tile the Finance group shows
data/files/expense_accounting_dashboard.json   the o-spreadsheet document (generated)
tools/gen_dashboard.py                         regenerates the JSON above
```

The dashboard record lives in `spreadsheet_dashboard.spreadsheet_dashboard_group_finance`
at **sequence 45**, immediately after the stock Expenses dashboard. Access is granted to
`account.group_account_readonly` and `account.group_account_invoice`.

### The stock Expenses dashboard is hidden (v17.0.3.2.0)

Finance used to list two tiles named "Expenses": this one, and the stock
`spreadsheet_dashboard_hr_expense` tile that reads `hr.expense` only. With costs booked
as vendor bills and journal entries, `hr.expense` holds **0 records**, so that tile was
permanently empty - and it surfaced for anyone in *Expenses / Administrator*.

`data/expense_dashboard.xml` therefore rewrites the stock record with
`group_ids = Command.clear()`. Visibility is a record rule on `spreadsheet.dashboard`
(`[('group_ids', 'in', user.groups_id.ids)]`), so an empty set takes the tile off the
list for everyone, admins included. Nothing is deleted and `hr_expense` is untouched -
the app, its menus and its data stay exactly as they were.

Two consequences to know:

- The record belongs to another module, so an upgrade of
  `spreadsheet_dashboard_hr_expense` (i.e. an Odoo version upgrade) restores its stock
  `group_ids` and the empty tile returns. Re-run `-u jito_expense_dashboard`;
  `tests/test_dashboard_visibility.py` fails loudly when this has happened.
- To bring it back on purpose, drop that one `<record>` and upgrade the module.

This is also why the module now depends on `spreadsheet_dashboard_hr_expense`: the
record it rewrites has to be loaded first.

## Constraints and gotchas

- **A long-running Odoo server does not learn about a new field on its own.** This module
  adds `account.move.line.expense_category_id`. A worker whose registry was loaded before
  the upgrade returns a `fields_get` without it, and then:
  *charts silently draw nothing* — `GraphModel` throws while preparing its metadata, so no
  `web_read_group` is ever sent (the giveaway is zero `web_read_group` lines in the log
  while the dashboard is open) — and *pivot cells come back empty*, because a failed
  `read_group` is returned as a JSON-RPC error inside an **HTTP 200**, so nothing looks
  broken in the access log. **Restart the server after `-u`.** The stale-registry symptom
  is selective: blocks that do not touch the new field (KPIs, Top vendors, Recent bills)
  keep working, which makes it look like a design bug rather than a stale process.
- **The trend exists twice on purpose.** The stacked chart is a live `GraphModel` query;
  the matrix below it is ordinary `ODOO.PIVOT` cells. Different code paths, same numbers,
  so the monthly trend stays readable even if the chart engine cannot draw.
- **Blocks are stacked vertically, not side by side.** Column `A` is the label column for
  every table, `B..K` are the month columns of the trend matrix and double as the
  Docs / Amount / % columns of the ranking tables, `L` is Total. Side-by-side tables would
  need two wide label columns, which the shared column widths cannot provide once a
  uniform month grid exists.
- **Do not hand-edit the JSON.** Change `tools/gen_dashboard.py`, run
  `python tools/gen_dashboard.py`, then `-u jito_expense_dashboard`. The spreadsheet is
  stored as an `ir.attachment` on the dashboard record; the file on disk is only the
  install-time seed, and an upgrade overwrites the stored attachment.
- **Bump the manifest version every time**, or the attachment is not refreshed.
- **Positional pivot access needs `sortedColumn`.** The idioms are the same ones the stock
  Odoo dashboards use — `=ODOO.PIVOT.HEADER(4,"#partner_id",3)` for the 3rd row header,
  `=ODOO.PIVOT(4,"balance","#partner_id",3)` for its measure, `=ODOO.LIST(1,3,"date")` for
  the 3rd list record. Without `sortedColumn` on the pivot, ordering is undefined.
- **Every data formula is wrapped in `IFERROR`.** Selecting a period with no records
  otherwise fills the tables with `#ERROR` instead of blanks.
- **Scorecards cannot hold formulas.** They reference cells, so the KPI formulas live on a
  hidden `Data` sheet (`isVisible: false`) and the scorecards point at `Data!B1..B8` /
  `Data!C1..C8`.
- **Figures float over the grid.** The title occupies rows 1–2, the figure band runs to
  roughly y=492px, and cell content therefore starts at row 25 (`TOP_ROW`). Moving a
  figure means re-checking that gap.
- **`Others` is a remainder, not a query.** It is `Total − SUM(top N)`. In the Top Vendors
  table that remainder also absorbs lines with no partner (journal entries — $1,821.93
  over the reference period), so the vendor table's Total matches the KPI while no
  individual vendor row accounts for those lines. The Expense structure table lists all
  nine categories, so its Others row is only insurance against a tenth being added later.
- **The list is deliberately narrower than the KPIs.** `journal_id.type = 'purchase'` keeps
  FX-revaluation pairs and bank-fee micro-lines out of "Recent vendor bills"; the KPIs stay
  unfiltered so they reconcile to the general ledger. The footnote on the sheet states
  this. On the reference data, 495 of 801 lines are purchase-journal lines, yet they carry
  99.2% of the money.
- **`__count` happens to equal the document count** on the reference data (801 lines across
  801 distinct moves — one expense line per document), which is why the KPI is labelled
  "Documents". If bills ever carry several expense lines, relabel it.
- **`balance` depends on FX rates at posting date.** Foreign-currency bills are converted
  by `jito_ecb_exchange_rate`; stale rates silently distort these figures.
- **o-spreadsheet has no runtime interactivity.** No live category switcher, no hover
  drill-down, no exploded pie slice. Anything of that kind needs an OWL client action, not
  a spreadsheet dashboard.

## Verified on odoo_dev (2026-07-31)

Trailing 365 days, 2025-08-01 → 2026-07-31. All figures from queries run against the
database, not estimates.

```
Total expenses      251 370.21   (801 lines / 801 documents)
Direct costs        133 785.75
Operating           117 584.46
In draft             19 800.00   (1 unposted line)
Previous period         450.00   (1 document)
```

Structure — the nine categories sum **exactly** to the ledger total:

```
Subcontractor           133 785.75   53.2%    67 lines
Uncategorized            69 201.80   27.5%    44
Platform fees            22 538.19    9.0%   414
SaaS & tools             15 037.63    6.0%   132
Professional services     5 181.33    2.1%     2
Meals & entertainment     3 025.88    1.2%    32
Office + FX               1 351.39    0.5%    68
Other                     1 001.65    0.4%     8
Bank & fees                 246.59    0.1%    34
                       -----------
                        251 370.21  = ledger, difference 0.00
```

31 of 31 expense accounts categorised, 0 move lines left without a category.
Trend chart: 58 month × category buckets. Top vendors: 85 partners, 249 548.28 with a
partner and 1 821.93 without.

**Known limitation of the comparison, not a defect:** the previous window
(2024-08-01 → 2025-07-31) contains only 450.00 across 1 document, because bookkeeping in
this database effectively starts in November 2025. The deltas on the trailing-365-day
range are therefore meaningless until roughly November 2026. They are already meaningful
on shorter ranges (Last 30 Days, Last 90 Days), which is what the offset mechanism was
built for.

**Open item:** *Uncategorized* is 27.5% of spend — account `600000 "Expenses"`, 44 lines
across 28 partners, and the largest lines are clearly subcontractor work (PALARRIGIM,
Koreon, outsourced UX/UI). No dashboard change can fix this; the bookkeeping has to move
those lines onto real accounts. The dashboard surfaces the number rather than hiding it,
which is the point.

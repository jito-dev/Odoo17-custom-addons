# jito_ledger_reports — Developer Guidance

## Module Purpose

`jito_ledger_reports` is **Phase 5** of the management-ledger feature
(see [`docs/HLD.md`](../../docs/HLD.md) and
[`docs/IMPLEMENTATION_PLAN.md`](../../docs/IMPLEMENTATION_PLAN.md) §8).

v1.0.0 shipped the **Management Trial Balance** — the foundational
report. 17.0.2.0.0 adds the **Partner Ledger** and promotes the
Reports section to a top-level **Reporting** menu under Management
Ledger (sibling of Accounting). 17.0.3.0.0 splits Partner Ledger into
three scope-specific entries under one report: **Management** (parallel
ledger only), **FAAP Projection** (LL surfaced via FAAP mirrors), and
**Combined** (both unioned). 17.0.5.0.0 adds the **Non-Leading General
Ledger** — per-account drill-down to journal items, mirroring stock
Odoo's GL but on `jito.ledger.move.line`. 17.0.10.0.0 removes the
**Categorized** reporting feature (handler, report record, client
action, and menu section) after the `jito.ledger.account.category`
model was deleted from `jito_ledger_core`; Trial Balance and General
Ledger now render flat per-account layouts with no category grouping.
Future versions add Management P&L, Management Balance Sheet, and
combined LL+Mgmt views via the same custom-handler pattern.

---

## Architecture

### Pattern

AbstractModel inheriting `account.report.custom.handler` (Odoo
Enterprise — `account_reports` module). Two hooks:

- **`_custom_options_initializer(report, options, previous_options=None)`**
  augments the report's options dict. We add `jito_rate_policy`
  (`period_end` (default) / `spot_today`) per FR-23 / HLD Decision #1.
- **`_dynamic_lines_generator(report, options, all_column_groups_expression_totals, warnings=None)`**
  returns a list of `(sequence, line_dict)` tuples. Each line_dict has
  `id`, `name`, `level`, `columns: [...]`, etc. Columns positionally
  map to the report's `column_ids` defined in XML.

Pattern verified at:
- `odoo17_enterprise/odoo/addons/account_reports/models/account_report.py:67-83, 6074-6147`
- `odoo17_enterprise/odoo/addons/account_reports/models/account_general_ledger.py:14-85`
- `odoo17_enterprise/odoo/addons/account_reports/data/general_ledger.xml:3-48`

### FX translation — frozen at posting (17.0.9.0.0 / NL 17.0.10.0.0 ADR)

The original FR-23 design (translate at report time, no rate
snapshot) was reversed in `jito_ledger_nl` 17.0.10.0.0. Posted
`jito.ledger.move.line` records now carry a stored `balance` /
`debit` / `credit` in company currency, frozen at posting time. All
three report handlers (Trial Balance, General Ledger, Partner Ledger)
read these columns directly with `read_group` — no
rate_map multiplication.

`_build_rate_map` and `_resolve_rate_date` remain on
`jito.ledger.report.handler.base` for transitional callers but are
no-ops in the current handlers; the `jito_rate_policy` option chip
(`period_end` / `spot_today`) is preserved on saved-filter dicts for
back-compat but is ignored by the read paths. They will be removed
in a future cleanup version.

For the historical FR-23 design (still relevant to understand how
the conversion math worked before the reversal):

### Historic — FX presentation translation (FR-23, pre-17.0.9.0.0)

The report stores nothing in company currency — it computes
presentation values **at render time** from the lines'
`amount_currency` and the rate at the report-period date (per
`jito_rate_policy`):

```
company_amount = source_amount × rate(source_currency → company_currency, at policy_date)
```

Where `policy_date` is:
- **`period_end`** (default) — `options.date.date_to` (the last day of
  the report's date range).
- **`spot_today`** — today's date.

Rate lookup uses `res.currency._get_rates(company, rate_date)`. When
no rate exists for the exact date, Odoo's standard nearest-prior
fallback applies.

This was the FR-23 design strict — no FX revaluation JEs posted, no
company-currency snapshot on `jito.ledger.move.line` (Decision #8).
**Reversed in `jito_ledger_nl` 17.0.10.0.0**: company-currency
amounts are now frozen at posting; reports read them directly. See
the section above and the ADR for rationale (CLR drift on calibrated
multi-currency moves).

---

## Models

### `jito.ledger.report.handler.base` (17.0.2.0.0)

**File:** `models/report_handler_base.py`

Shared AbstractModel that all report handlers inherit. Hosts the
helpers that were previously duplicated on the Trial Balance handler:

- `_build_domain(options, date_from, date_to, *, model_name='jito.ledger.move.line', include_drafts=False)` —
  posted (unless `include_drafts`), non-voided, in date range, scoped
  to the user's allowed companies. The clause shape adapts to
  `model_name`:
  - `jito.ledger.move.line` (default) — adds `move_state='posted'`
    and `move_id.is_voided=False`.
  - `jito.ledger.statutory.view` — adds `state='posted'` (the SQL view
    is already posted-only; the clause is a safety net).
  - `account.move.line` — adds `parent_state='posted'`.
  Raises `ValueError` for any other `model_name`.
- `_resolve_date_range(options)` — pulls `(date_from, date_to)` from
  `options['date']`, defaulting to (Jan-1, today).
- `_resolve_rate_date(options, date_to)` — picks the FX-translation
  date per `jito_rate_policy`.
- `_build_rate_map(rate_date, company)` — `{currency_id:
  rate-from-tx-to-company}`.
- `_make_money_column(currency, value)` — column dict for a monetary
  cell.

> **Removed in 17.0.10.0.0:** the `_bucket_accounts_by_category`
> helper was deleted along with the whole category feature (the
> `jito.ledger.account.category` model was removed from
> `jito_ledger_core`). Trial Balance and General Ledger no longer
> group accounts by category — both render a flat per-account layout.

Both `JitoTrialBalanceCustomHandler` and
`JitoPartnerLedgerCustomHandler` inherit this. New report handlers
should too.

### `jito.ledger.trial.balance.report.handler`

**File:** `models/trial_balance_handler.py`

AbstractModel — no DB table. The custom handler registered with the
Trial Balance `account.report` record.

**`_dynamic_lines_generator` flow:**

1. Resolve date range from `options.date` (date_from / date_to).
2. Resolve the rate-translation date per `jito_rate_policy`:
   `period_end` → date_to; `spot_today` → today.
3. Build the rate map for all currencies → company currency at the
   resolved date.
4. Domain filter: posted, non-voided `jito.ledger.move`, in companies
   the user has access to, in the date range.
5. `read_group` aggregating `amount_currency:sum` per
   `(account_id, currency_id)`.
6. For each (account, currency, net_tx) bucket: translate
   `net_tx × rate` → company-currency amount. Accumulate per account
   into debit (positive) or credit (negative).
7. Build report lines: one per account, sorted by `account.code`. Each
   line has columns `[debit, credit, balance]`.
8. Emit a grand Total line at the bottom with summed totals.

This is a **single flat per-account layout** — one row per account
plus a grand Total. There is no category grouping and no render-mode
switch (the `jito_tb_mode` option and its `categorized` /
`category_summary` layouts were removed in 17.0.10.0.0). Only
`_render_flat` remains.

**Performance note:** uses ORM `read_group`. For v1 volumes (≤ 100k
lines per period) this is comfortable. For larger tenants, switch to
direct SQL — see the `_query_values()` helper pattern in stock
account_general_ledger.py:46-85.

### `jito.ledger.partner.ledger.report.handler` (17.0.2.0.0; scope toggle in 17.0.3.0.0)

**File:** `models/partner_ledger_handler.py`

AbstractModel inheriting `account.report.custom.handler` +
`jito.ledger.report.handler.base`. Mirrors stock partner ledger shape.

**Scope option** (`options['jito_data_scope']`, 17.0.3.0.0):
- `management` (default) — read `jito.ledger.move.line` only.
- `faap` — read `jito.ledger.statutory.view` only (LL lines projected
  through FAAP mirrors). The view is posted-only; the draft toggle is
  a no-op here.
- `combined` — read both sources, partner-aggregated. Drill-down rows
  carry a `[MGT]` or `[FAAP]` source tag prefix.

Scope resolution order (in `_custom_options_initializer`):
``previous_options['jito_data_scope']`` → context
``default_jito_data_scope`` (set by each action record) → `management`
default. Stock `account.report` doesn't render custom dropdown filters
without an OWL extension, so each scope has its own action + menu
entry rather than an in-report toggle (see Menu section).

The per-source reads live in three helpers: `_query_partner_period`,
`_compute_initial_balances`, and `_fetch_partner_lines`. The
`SCOPE_SOURCES` constant at the top of the file maps each scope value
to a list of ``(src_tag, model_name)`` tuples, so adding a new scope
in future is a one-line registry update + helper extension.

**`_dynamic_lines_generator` flow** (parent rows):

1. Resolve date range + draft-inclusion (from `options.show_draft`
   / `all_entries`).
2. Aggregate `jito.ledger.move.line` filtered to
   `partner_id != False` over the period: `read_group` by
   `(partner_id, currency_id)` summing `amount_currency`. Translate
   each bucket to company currency via the inherited rate map. Split
   into debit (positive) / credit (-negative) sums per partner.
3. Compute per-partner **initial balance**: same shape, filtered to
   `date < date_from`. Combined with period activity to produce the
   period-end Balance column.
4. Emit one unfoldable parent row per partner with
   `[debit_period, credit_period, balance_at_end]` columns and
   `expand_function = '_jito_report_expand_partner_ledger_line'`.
5. Trailing Total row sums per-partner debit / credit / balance.

**Expand callback** (`_report_expand_unfoldable_line_jito_partner_ledger` — the `_report_expand_unfoldable_line_` prefix is enforced by the stock `account.report` framework):

- First page emits an "Initial Balance" row, then iterates the
  partner's `jito.ledger.move.line` records (`order='date, id'`) in
  the period producing `[date, journal, account, ref, debit, credit,
  amount_currency, running_balance]` columns.
- Running balance starts at the partner's initial balance and
  accumulates per row (translated to company currency).
- v1 returns the full list (`has_more=False`); pagination is a v1.x
  improvement once profiling justifies.

**Partner filter:** `_partner_filter_from_options` reads
`options['partner_ids']` (populated by the report engine when
`filter_partner=True` is on the report record). Falsy → no filter.

---

## XML — `data/account_report.xml`

The `account.report` record:

- `name = "Management Trial Balance"`.
- `filter_journals = True` — standard Odoo journal filter (filters by
  `journal_id`).
- `filter_date_range = True` — standard Odoo period selector.
- `filter_multi_company = "selector"` — multi-company picker.
- `custom_handler_model_id` → `model_jito_ledger_trial_balance_report_handler`
  (auto-resolved from the AbstractModel's `_name`).

Three columns: Debit, Credit, Balance, all `figure_type="monetary"`.

The matching `ir.actions.client` (tag `account_report`) renders the
report when the menu is clicked.

---

### `jito.ledger.general.ledger.report.handler` (17.0.5.0.0)

**File:** `models/general_ledger_handler.py`

AbstractModel inheriting `account.report.custom.handler` +
`jito.ledger.report.handler.base`. Mirrors stock GL shape — parent
rows per `jito.ledger.account`, with on-demand drill-down to the
underlying journal items in date order with a running balance.

**Source:** `jito.ledger.move.line` only. Single-source by design
(see _Common pitfalls_ for rationale).

**`_dynamic_lines_generator` flow** (parent rows):

1. Resolve date range + draft-inclusion + rate map.
2. `_query_account_period` — split read_group by `amount_currency`
   sign (>0 → debit branch, <0 → credit branch), grouped by
   `(account_id, currency_id)` summing `amount_currency`. Translate
   per-currency totals to company currency via the rate map. This
   per-sign split keeps parent debit / credit aligned with the
   children's column sums (the invariant Partner Ledger established
   in 17.0.4.2.0).
3. `_compute_initial_balances` — same domain shape with
   `date < date_from` and `account_id IN account_ids`. Signed sum
   (positive = debit-side).
4. Emit one unfoldable parent row per account (sorted by
   `account.code`) with `[period_debit, period_credit, initial +
   period_debit − period_credit]` numeric columns. Caret options
   `jito.ledger.account` (`Open` + auto-appended `Annotate`).
5. Trailing `Total` row sums period debit / credit.

This is a **flat per-account layout** — no per-category header /
subtotal rows are emitted (category grouping was removed in
17.0.10.0.0). Just per-account rows plus the grand Total.

**Expand callback** (`_report_expand_unfoldable_line_jito_general_ledger`):

- First page emits an "Initial Balance" row, then iterates the
  account's `jito.ledger.move.line` records (`order='date, id'`) in
  the period producing `[Date, Communication, Partner, Debit,
  Credit, Amount Currency, running Balance]` columns.
- Running balance starts at the initial balance and accumulates per
  row (each line's `amount_currency` translated to company currency
  via the rate map).
- Child rows carry `caret_options='jito.ledger.move.line'` → 3-dots
  dropdown with "View Journal Entry" + auto-appended "Annotate".
- v1 returns the full list (`has_more=False`); pagination is a v1.x
  improvement once profiling justifies.

**Partner filter:** the standard `options['partner_ids']` flows
through to `_query_account_period`, `_compute_initial_balances`, and
`_fetch_account_lines` — pick a partner from the filter chip and
every account row + child row narrows to that partner's activity.

---

## Menu (17.0.10.0.0)

```
Management Ledger
├── Ledgers
├── Customers
├── Vendors
├── Accounting
│   ├── Journals
│   └── Adjustments
├── Reporting                       ← 17.0.2.0.0 (own section)
│   ├── Trial Balance               ← flat per-account layout
│   ├── Non-Leading Ledger          ← 17.0.5.1.0 subfolder
│   │   ├── General Ledger          ← 17.0.5.0.0
│   │   └── Partner Ledger          ← 17.0.4.0.0 mgmt-only
│   ├── LL + NL + EXT               ← 17.0.6.0.0 subfolder
│   │   ├── General Ledger          ← combined scope
│   │   └── Partner Ledger          ← combined scope
│   └── Analytic Reporting          ← 17.0.4.1.0
└── Configuration
```

> The **Categorized** subfolder (General Ledger (All Categories),
> Trial Balance categorized) was removed in 17.0.10.0.0 together with
> the `jito.ledger.account.category` model.

The **Non-Leading Ledger** subfolder groups the per-account and
per-partner drill-down reports so the top-level Reporting menu stays
uncluttered. The parent menu's "Non-Leading" qualifier lets the
children drop the prefix, so the labels are short ("General Ledger",
"Partner Ledger") while still reading unambiguously as the
parallel-ledger views — not the stock Odoo reports of the same name.
The report records' own `name` field still carries the "Non-Leading"
prefix so the breadcrumb and any export filename keeps the
disambiguation.

The **LL + NL + EXT** subfolder (17.0.6.0.0) shows the same two
reports but unions all three ledger sources. Same `account.report`
records, same columns, same filters — only `default_jito_data_scope`
is different in the action context (`combined` vs `management`).
The handlers' `SCOPE_SOURCES` registry expands `combined` into:

  * `jito.ledger.move.line` — NL + EXT (the EXT entry_type is just a
    discriminator on the same NL storage; no separate table).
  * `jito.ledger.statutory.view` — LL `account.move.line` projected
    onto NL accounts via `jito.ledger.account.statutory_account_id`
    (the FAAP mapping).

Drill-down rows in combined scope are prefixed with `[MGT]` or
`[FAAP]` in the row label so the user can tell which side each line
came from.

**Why management-only?** Crypto-driven workflows post directly into
`jito.ledger.move` and never touch stock `account.move`, so the
FAAP Projection / Combined scopes shipped in 17.0.3.0.0 added noise
without insight for this product. The handler still recognises
`default_jito_data_scope` set to `faap` or `combined` for any
programmatic caller that wants them, but no menu action exposes them.

---

## Scope and Limits (v1.0.0)

**Shipped:**
- Single-period view.
- Per-account rows in the management chart of accounts
  (`jito.ledger.account`).
- FX presentation translation per `jito_rate_policy`.
- Standard journal / date-range / multi-company filters.

**Out of scope (v1.x):**
- Management P&L (revenue / expenses categorisation).
- Management Balance Sheet (asset / liability / equity hierarchy).
- Combined LL + Mgmt view (joining `account.move.line` and
  `jito.ledger.move.line` in one report).
- Comparison-period columns (column_groups).
- On-the-fly drill-down to the `jito.ledger.move.line` records driving
  each account total.
- Hierarchical grouping by `account.group` / semantic family.
- Open CLR aging report (a more specialised view of unresolved
  bridging balances; relates to Phase 4 but lives here).

---

## Verification (Phase 5)

After installing the module:

1. **Install completes** without errors. `account_reports` (Enterprise)
   should already be installed via Phase 5's manifest dependency.
2. **Menu visible** at Management Ledger → Accounting → Reports →
   Trial Balance. Click it.
3. **Empty state** if no posted moves yet — shows "Total" line with
   zeros.
4. **Pre-test setup:**
   - Have FAAP/MGT/CLR/GRP child accounts (run FAAP sync if not done).
   - Post some `jito.ledger.move` entries (NL docs, restatements,
     bridgings, regroupings — anything from Phase 2/4).
5. **Render check** — click Trial Balance.
   - All accounts with activity appear, sorted by code.
   - Debit / Credit / Balance show in your company currency.
   - Total at the bottom — Debit and Credit columns should equal
     (modulo per-currency rounding from FX translation).
6. **Date range** — narrow the period; rows recompute.
7. **Multi-currency** — post a USDC NL entry. The Trial Balance shows
   the USDC value translated to company currency.
8. **Rate-policy switching** — *(present in options dict but no UI
   selector yet in v1.0.0)*. To verify FX, change the
   `res.currency.rate` for USDC to a new rate and re-run; numbers
   should change. Adding a UI dropdown for `jito_rate_policy` is a
   v1.0.x improvement.
9. **Voided moves hidden** — destructively reverse a posted move
   (Phase 4 feature); reload the Trial Balance — that move's
   contribution disappears (per the `is_voided=False` filter).

### Partner Ledger (17.0.2.0.0)

1. **Menu shape** — Management Ledger now shows **Reporting** as a
   top-level section (not nested under Accounting). Both Trial Balance
   and Partner Ledger live under it.
2. **Click Partner Ledger.** With at least one posted invoice in the
   period (e.g. via `jito_ledger_nl`'s Customer Invoices), confirm:
   - One unfoldable parent row per partner with activity.
   - Debit / Credit / Balance columns in company currency.
   - Period defaults to "This Year"; multi-company picker present.
3. **Drill-down** — click a partner row → first child is an
   "Initial Balance" line (sum of transactions before the period);
   subsequent children show each `jito.ledger.move.line` with
   `Date / Journal / Account / Ref / Debit / Credit / Amount Currency /
   Running Balance`.
4. **Show Draft toggle** — open the report's options panel, enable
   "Show draft entries"; draft moves now appear. Toggle off → they
   vanish.
5. **Partner filter** — pick a single partner via the filter chip;
   only that partner's row + drill-down render.
6. **Multi-currency** — for a partner with EUR + USD lines, confirm
   the Balance is presented in company currency via the same
   `_build_rate_map` Trial Balance uses.

### LL + NL + EXT subsection (17.0.6.0.0)

1. **Menu** — Reporting now has a sibling subfolder **LL + NL + EXT**
   next to Non-Leading Ledger. It contains its own **General Ledger**
   and **Partner Ledger** entries — same report records as the
   Non-Leading entries, just opened with `default_jito_data_scope='combined'`.
2. **Combined Partner Ledger** —
   * Setup: a partner with at least one stock invoice
     (`account.move.line`) and one NL move (`jito.ledger.move.line`)
     in the same period.
   * Open it; the partner row should show period Debit / Credit
     summing both sides; Balance reflects the unified picture.
   * Drill down — child rows are prefixed `[MGT]` (from
     `jito.ledger.move.line` — NL+EXT) or `[FAAP]` (from
     `jito.ledger.statutory.view` — LL projected). Total at the
     bottom = MGT total + FAAP total per the corresponding columns.
3. **Combined General Ledger** —
   * Setup: a `jito.ledger.account` with `statutory_account_id` set,
     LL postings to the mapped `account.account`, and an NL move on
     the NL account.
   * Open it; the account's parent row should sum both sides;
     drill-down child rows show `[MGT]` / `[FAAP]` prefixes and the
     running balance accumulates across sources by date.
4. **EXT lines visible** — post an entry with
   `entry_type='ext_adjustment'` (via `jito_ledger_extension`).
   It should appear in BOTH the Non-Leading and the LL+NL+EXT views
   (EXT lives in NL storage; not double-counted).
5. **LL-without-mapping caveat** — post an LL move to an
   `account.account` that has **no** `jito.ledger.account.statutory_account_id`
   pointing at it. That LL line is intentionally invisible in the
   combined General Ledger (the FAAP projection drops it). See
   _Common pitfalls_ below.

### Non-Leading General Ledger (17.0.5.0.0)

1. **Menu** — Management Ledger → Reporting → **Non-Leading General
   Ledger**. Opens with date range "This Year" by default.
2. **Parent rows** — one unfoldable row per `jito.ledger.account`
   with activity in the period, sorted by code. Columns: Date /
   Communication / Partner are blank; Debit / Credit / Balance show
   per-account totals in company currency.
3. **Drill-down** — click an account row. First child is an
   "Initial Balance" line (sum before the period); subsequent
   children list each `jito.ledger.move.line` with date,
   communication (move ref / line label), partner, debit, credit,
   amount currency (e.g. "100.00 USDT" if non-company currency),
   and a running balance.
4. **Caret menus** — 3-dots on an account row: **Open** (form view) +
   **Annotate**. 3-dots on a child line: **View Journal Entry** +
   **Annotate**.
5. **Show Draft toggle** — open the options panel, enable "Show
   draft entries"; drafts appear in both period sums and drill-down.
6. **Journal filter** — pick one or more journals; only their lines
   contribute.
7. **Partner filter** — narrows every account row + child row to
   that partner's activity (period sums recompute).
8. **Multi-currency** — for an account that has both EUR and USDC
   lines, parent totals are company-currency sums; child rows show
   the original `amount_currency` next to the translated company
   values.

### Partner Ledger scope toggle (17.0.3.0.0)

1. **Menu shape** — under Reporting, Partner Ledger is now a folder
   with three children: **Management**, **FAAP Projection**, **Combined**.
2. **Management** entry — confirm it matches the 17.0.2.0.0 behavior
   (sums of `jito.ledger.move.line` only).
3. **FAAP Projection** entry — same partner totals as stock Odoo's
   Partner Ledger restricted to FAAP-mirrored accounts; drafts toggle
   is a no-op (the view filters drafts out).
4. **Combined** entry — totals = Management + FAAP for each partner.
   Drill-down rows are prefixed with `[MGT]` or `[FAAP]` so you can
   tell which side a line came from. Verify against
   `Management.total + FAAP.total` for at least one partner.

---

## Common pitfalls

- **`account_reports` license:** Enterprise (OEEL-1). The module's
  manifest dependency will fail to resolve if the user's Odoo install
  doesn't have Enterprise addons in its addons-path.
- **Custom handler `_name`:** Odoo auto-creates the matching `ir.model`
  record (`model_<snake_case_name>`) which the `custom_handler_model_id`
  ref points at. If the AbstractModel's `_name` changes, the XML ref
  breaks — bump major version + migration.
- **Column ordering:** the line dict's `columns: [...]` is positional.
  Adding a new column in XML requires updating the
  `_dynamic_lines_generator` to return one more item per line.
- **`read_group` deprecation:** Odoo 17 still supports `read_group`
  but a future release will replace it. Migrate to `_read_group` or
  direct SQL when convenient.
- **GL `combined` scope (17.0.6.0.0):** The General Ledger handler
  gained `SCOPE_SOURCES` in 17.0.6.0.0, mirroring the Partner Ledger
  pattern. Only `management` and `combined` scopes are wired (the
  standalone `faap` scope is intentionally omitted — the LL-only
  General Ledger is already covered by stock Odoo's GL).
- **LL-without-mapping caveat (combined GL):** LL accounts that have
  no inverse `jito.ledger.account.statutory_account_id` mapping
  **do not appear** in the combined General Ledger. The `combined`
  scope routes LL through `jito.ledger.statutory.view`, which only
  surfaces LL lines whose stock `account.account` is the target of
  some `jito.ledger.account.statutory_account_id`. If you want full
  LL coverage in the combined GL, ensure every relevant
  `account.account` has at least one `jito.ledger.account` pointing
  at it. The combined Partner Ledger does not share this limitation:
  `partner_id` (`res.partner`) is the same FK on both ledgers, so no
  mapping is required.

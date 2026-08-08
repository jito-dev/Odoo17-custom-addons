# Changelog - Rate Card Management Module

## Version 1.18.0 (2026-08-08)

### Timesheet totals bar: one row, aligned with the columns

- **Totals were left-aligned while the values below them were right-aligned.** Core
  right-aligns `.o_list_number` only under `tbody > tr > td` and under `tfoot`
  (`list_renderer.scss:91, 143`). The bar lives in `<thead>`, so it matched neither
  rule. Added the alignment (plus `direction: ltr`) for the row's own cells.
- **Two rows became one.** The separate caption row is gone; its information is now a
  short label inside the bar itself — `Totals`, or `Totals · 80 of 700` when the
  aggregates only cover the loaded page. The full sentence moved to a tooltip.
- The label **spans** the columns before the first total instead of sitting in the
  first cell: in a timesheet list that cell is Date, far too narrow for it, and
  `freezeColumnWidths()` measures the table with `table-layout: auto`
  (`list_renderer.js:341-374`), so a long string in one cell would widen that column.
- For the same reason the bar is now hidden during the width-measuring pass
  (`.o_list_computing_widths`), so it cannot influence column widths at all.
- Given a background of its own (`$o-view-background-color`, the colour of the data rows)
  and a border on both edges, so it reads as a bar rather than as one more line of the
  grey header block. Note `$o-list-footer-bg-color` is `transparent` in Odoo — the
  standard footer is bold text, not a filled plate — so it is deliberately not used here.
- The bar is no longer rendered when no displayed column carries an aggregate.
- Assets only — no model, view-XML or data change.

---

## Version 1.17.0 (2026-08-08)

### Adjusted Hours precision reverted to the pre-1.14.8 behaviour

Business decision: the only timesheet change that was needed is the 15/30-minute
rounding of tracked hours (`jito_timesheet_rounding`). Everything built around
displaying off-grid durations is rolled back, here and in that module's XLSX export.

- `account.analytic.line.tm_adjusted_hours`: `digits=False` → `digits='Hours'`. As
  before, `'Hours'` is not a registered `decimal.precision` and resolves to 2 digits,
  so the ORM rounds every write. With tracked hours on a quarter-hour grid, the values
  this field carries (0.25 / 0.5 / 0.75 / 1.0 …) are exact in 2 decimals.
- Auto-sync in `write()`: `float_compare(..., precision_digits=5)` → `==`, and
  `ADJUSTED_HOURS_SYNC_PRECISION` plus the `float_compare` import are removed.
- **No column change and no data migration.** `Float.column_type` returns `numeric`
  for both `False` and `'Hours'` (`odoo/fields.py:1513`), so no `ALTER COLUMN TYPE`
  is issued and stored rows are untouched. Rows written between 1.14.8 and 1.17.0
  keep their full precision until they are next written through the ORM.
- **Accepted residual 1:** the grid applies to `unit_amount`, not to
  `tm_adjusted_hours`. A PM entering an off-grid billing correction (1:10) still gets
  `1.17` stored.
- **Accepted residual 2 — known defect, measured before shipping.** An entry typed
  off-grid ends up with Adjusted Hours that do not match its rounded logged hours
  (1:07 → logged 1.00, adjusted 1.12), and the mismatch is permanent because the
  auto-sync reads it as a manual adjustment. `create()` copies Adjusted Hours from the
  un-rounded `unit_amount` before `jito_timesheet_rounding` snaps it. On-grid entries
  are unaffected. See GUIDANCE.md §5 for the two available fixes — deliberately not
  applied, since this release is a revert to the `main` branch state.

---

## Version 1.16.0 (2026-08-07)

### Timesheet totals moved to the top of the list

- The aggregates (and their caption) are now repeated inside `<thead>` instead of the
  footer being pinned to the bottom of the viewport. The standard footer goes back to its
  default, non-sticky behaviour.
- Reason: `position: sticky` resolves against the element's own place in the flow, and
  `<tfoot>` always follows `<tbody>` — pinning it with `top` engages only after the whole
  table has scrolled past, so totals can never sit above the rows. Core already makes
  `thead` sticky as a whole element (`web/views/list/list_renderer.scss:16-19`), so a row
  placed there is pinned with no positioning code of our own.
- The header cells are `<td>`, never `<th>`: core resolves sorting, resizing and column
  widths through `thead th` (`list_renderer.js:180, 347, 408, 428, 2150`), and `<th>` would
  enrol the totals row in all three.
- No Python, model or view-XML change; assets only.

---

## Version 1.15.0 (2026-08-07)

### Billable Amount total + permanently visible timesheet totals

**Total for the Billable Amount column (was `—`):**
- New computed (not stored) field `account.analytic.line.tm_billable_currency_id`:
  `tm_billing_currency_id or company_id.currency_id`. Timesheets without a rate card
  carried no currency at all, which makes the list footer refuse to aggregate the
  monetary column; their amount is 0.00, so the fallback changes no total.
- Timesheet tree view: `tm_billable_amount` gains `sum="Total Billable"` and
  `options="{'currency_field': 'tm_billable_currency_id'}"`; the currency field is added
  as a `column_invisible` column, which the footer requires to aggregate at all
  (`web/views/list/list_renderer.js:696-707`).
- `tm_billable_amount.currency_field` itself is unchanged, so other views are untouched.

**Totals stay visible while scrolling:**
- New view class `tm_timesheet_totals_list` (`static/src/js/timesheet_totals_renderer.js`),
  attached to `hr_timesheet.timesheet_view_tree_user`: sticky `tfoot` (desktop) plus a
  caption row stating how many records the totals cover when the page is not the whole
  result. Ungrouped lists aggregate only the loaded page (limit 80); grouped lists use
  `read_group` and get no caption.

---

## Version 1.14.6 (2026-02-24)

### Bug Fixes

**Issue 1 — Project field now filtered to customer's projects:**
- `project_id` field on the Rate Card Entry form now has `domain="[('partner_id', '=', client_id)]"`, restricting choices to projects belonging to the selected Sales Order's customer.
- `_onchange_sale_order_id` now also clears `project_id` when the SO changes and the selected project no longer belongs to the new client.

**Issue 3 — Currency display fix in Validated Timesheet Statistics:**
- Added `tm_billing_currency_id` stored related field on `account.analytic.line` (from `tm_rate_card_entry_id.currency_id`).
- Changed `currency_field` for `tm_billing_rate` and `tm_billable_amount` from `currency_id` (company currency) to `tm_billing_currency_id` (billing currency from Rate Card Entry).
- Timesheet tree view within RCE now shows "Billing Currency" column instead of generic "Currency".
- Post-init hook backfills `tm_billing_currency_id` for existing timesheets.

---

## Version 1.2.0 (2026-01-27)

### 🆕 New Feature: Fully Optional Date Ranges

**Both `date_start` and `date_end` are now optional, supporting all four combinations**

#### What Changed

**`date_start` is now optional** (previously required)

This enables maximum flexibility for rate card effective periods:

1. **Set + Set** (both dates specified)
   - Example: Valid from 2026-01-01 to 2026-12-31
   - Most specific date range

2. **Set + Undefined** (only start date)
   - Example: Valid from 2026-01-01 onwards forever
   - Display: `2026-01-01 → ∞`

3. **Undefined + Set** (only end date) - **NEW!**
   - Example: Valid from beginning of time until 2026-12-31
   - Display: `∞ → 2026-12-31`
   - Use case: Legacy rates or rates valid "until superseded"

4. **Undefined + Undefined** (no dates) - **NEW!**
   - Example: Valid for all time
   - Display: `∞ ↔ ∞ (all time)`
   - Use case: Default/perpetual rates

#### Updated Logic

**Overlap Constraint:**
- Enhanced to handle all four date combinations
- Correctly detects overlaps for indefinite past/future ranges
- NULL dates treated as infinity in overlap calculations

**Rate Resolution Service:**
- Updated domain filters to match rates with NULL dates
- `date_start = NULL` means valid from beginning of time
- `date_end = NULL` means valid forever onwards

**Display Names:**
- Rate cards now show intuitive date range labels:
  - `∞ ↔ ∞ (all time)` for both NULL
  - `∞ → 2026-12-31` for NULL start
  - `2026-01-01 → ∞` for NULL end
  - `2026-01-01 → 2026-12-31` for both set

#### UI Updates

**Form View:**
- Updated help text to clarify both dates are optional
- Shows all four combination options
- No required indicator on `date_start` field

**Error Messages:**
- Overlap errors now show "indefinite past" or "indefinite future" for NULL dates
- Clear communication of date range in all scenarios

#### Use Cases

**Use Case 1: Default Rate (All Time)**
```
Rate Card:
- Client: ACME Corp
- Employee: John Doe
- Service: Dev Hour
- Rate: $150/hour
- Valid From: (blank)
- Valid Until: (blank)
- Display: ∞ ↔ ∞ (all time)

Result: This rate applies for any date if no more specific rate exists
```

**Use Case 2: Legacy Rate (Valid Until Replaced)**
```
Rate Card:
- Client: ACME Corp
- Employee: Jane Smith
- Service: Dev Hour
- Rate: $100/hour
- Valid From: (blank)
- Valid Until: 2025-12-31
- Display: ∞ → 2025-12-31

Rate Card:
- Client: ACME Corp
- Employee: Jane Smith
- Service: Dev Hour
- Rate: $125/hour
- Valid From: 2026-01-01
- Valid Until: (blank)
- Display: 2026-01-01 → ∞

Result: Clean transition from old to new rate
```

**Use Case 3: Future Rate (From Date Onwards)**
```
Rate Card:
- Client: ACME Corp
- Employee: John Doe
- Service: Dev Hour
- Rate: $175/hour
- Valid From: 2026-06-01
- Valid Until: (blank)
- Display: 2026-06-01 → ∞

Result: Rate increase effective June 2026, no end date
```

#### Breaking Changes

**None** - This is backward compatible.

- Existing rate cards with `date_start` set continue to work unchanged
- No data migration required
- Optional dates are additive functionality

#### Technical Details

**Model Changes:**
- `date_start`: `required=True` → `required=False`
- Updated help text for both date fields
- Updated `_check_no_overlap()` constraint with comprehensive date logic:
  - Case 1: NULL+NULL → matches everything
  - Case 2: Set+NULL → matches if other overlaps our start→∞
  - Case 3: NULL+Set → matches if other overlaps ∞→our end
  - Case 4: Set+Set → existing logic enhanced for NULL dates

**Resolution Service:**
- Updated `resolve_rate()` base domain:
  - `date_start <= date OR date_start IS NULL`
  - `date_end >= date OR date_end IS NULL`

**Display Name:**
- Updated `_compute_name()` to show all four combinations clearly

**Views:**
- Updated form view help text
- No visual changes to tree/search views

---

## Version 1.1.0 (2026-01-27)

### 🆕 New Features: Sales Order Integration

**Added Sales Order linking to rate cards for enhanced traceability**

#### New Fields

1. **`sale_order_id`** (Many2one to `sale.order`)
   - Optional field to link rate card to a specific Sales Order
   - Provides contractual authorization context
   - Domain filtered by client and confirmed orders (state = 'sale' or 'done')

2. **`sale_order_line_id`** (Many2one to `sale.order.line`)
   - Optional field to link rate card to a specific SO line item
   - Domain automatically filtered by selected `sale_order_id` and `client_id`
   - Auto-populates `service_product_id` when selected

#### Smart Auto-Fill Behavior

**When you select a Sales Order Line:**
- ✅ Automatically fills `sale_order_id` from the line's order
- ✅ Automatically fills `service_product_id` from the line's product
- ✅ Automatically fills `client_id` from the SO's partner (if not already set)
- ✅ Automatically fills `currency_id` from the SO's currency

**When you select a Sales Order:**
- ✅ Automatically fills `client_id` from the SO's partner (if not already set)
- ⚠️ Clears `sale_order_line_id` if it doesn't belong to the new SO

#### Updated Unique Combination

The overlap prevention constraint now includes `sale_order_line_id` in the unique combination:
```
(company, client, service_product, employee, currency, project, sale_order_line)
```

This means you can have:
- Multiple rate cards for the same employee/client/product but **different SO lines**
- This allows different rates for the same service depending on which contract (SO) it's billed under

#### Updated Immutability Rules

The new SO fields are **pricing-critical**:
- `sale_order_id` and `sale_order_line_id` are **locked** when state = `locked` or `invoiced_locked`
- Cannot be changed after rate card is used by validated timesheets

#### UI Updates

**Tree View:**
- Added `sale_order_id` column (optional, visible by default)
- Added `sale_order_line_id` column (optional, visible by default)

**Form View:**
- Added SO fields in "Dimensions" section, between `project_id` and `service_product_id`
- SO line dropdown filtered by selected SO and client
- Service product auto-populated when SO line selected

**Search View:**
- Added search by `sale_order_id` and `sale_order_line_id`
- Added filter: "Linked to Sales Order" (has SO)
- Added filter: "Not Linked to SO" (no SO)
- Added group by: "Sales Order"

**Display Name:**
- Rate card names now include SO reference when linked: `[.../ SO: SO001 /...]`

---

### 📝 Use Cases

#### Use Case 1: Contract-Specific Rates
```
Scenario: Different rates for same employee on different client contracts

Rate Card A:
- Client: ACME Corp
- SO: SO001 (Premium Support Contract)
- SO Line: Premium Dev Hours
- Employee: John Doe
- Rate: $200/hour

Rate Card B:
- Client: ACME Corp
- SO: SO002 (Standard Development)
- SO Line: Standard Dev Hours
- Employee: John Doe
- Rate: $150/hour

Result: John's rate varies by which contract the work is billed under
```

#### Use Case 2: Traceability to Contract Authorization
```
Scenario: Finance needs to verify rate card is authorized by a signed contract

Rate Card:
- Client: ACME Corp
- SO: SO001 (Confirmed Sales Order = contractual authorization)
- SO Line: Line 2 (Dev Hours - $150/hr, Qty: 500)
- Employee: Jane Smith
- Rate: $150/hour

Result: Clear audit trail showing rate is authorized by SO001
```

#### Use Case 3: Flexible Rate Management
```
Scenario: Some rates are contractual, others are client-wide defaults

Rate Card A (Contractual):
- Client: ACME Corp
- SO: SO001
- SO Line: Senior Dev Hours
- Rate: $175/hour

Rate Card B (Default - No SO):
- Client: ACME Corp
- SO: (blank)
- SO Line: (blank)
- Rate: $150/hour (fallback rate)

Result: Both coexist - different unique combinations (one has SO line, one doesn't)
```

---

### 🔧 Technical Changes

#### Model Changes (`tm_rate_card_entry.py`)

1. **New Fields:**
   ```python
   sale_order_id = fields.Many2one('sale.order', ...)
   sale_order_line_id = fields.Many2one('sale.order.line', ...)
   ```

2. **New Onchange Methods:**
   - `_onchange_sale_order_line_id()` - Auto-fill from SO line
   - `_onchange_sale_order_id()` - Clear SO line if SO changes

3. **Updated Constraint:**
   - `_check_no_overlap()` now includes `sale_order_line_id` in domain

4. **Updated Immutability:**
   - `PRICING_CRITICAL_FIELDS` now includes `sale_order_id`, `sale_order_line_id`

5. **Updated Display Name:**
   - `_compute_name()` includes SO reference

#### Manifest Changes (`__manifest__.py`)

- **Version:** 1.0.0 → 1.1.0
- **New Dependency:** Added `sale` module
- **Updated Description:** Mentions Sales Order integration

#### View Changes (`tm_rate_card_entry_views.xml`)

- Tree view: Added SO columns
- Form view: Added SO fields with proper domains and context
- Search view: Added SO filters and group by

---

### ⚠️ Breaking Changes

**None** - This is a backward-compatible update.

- Existing rate cards continue to work (SO fields are optional)
- Old unique combinations still valid (NULL SO line is distinct from any SO line)
- No data migration required

---

### 📦 Upgrade Instructions

#### For Existing Installations

1. **Update module code** from repository
2. **Upgrade module** in Odoo:
   ```bash
   # Via UI:
   Apps → Rate Card Management → Upgrade

   # Or via command line:
   odoo-bin -d <database> -u tm_rate_card --stop-after-init
   ```
3. **Clear browser cache** (Ctrl+F5 or Cmd+Shift+R)
4. **Verify** new fields appear in form view

**No data migration needed** - existing rate cards remain valid.

---

### 🧪 Testing Recommendations

1. **Create rate card with SO line:**
   - Select client
   - Select confirmed SO for that client
   - Select SO line → verify service product auto-fills
   - Save and verify all fields persisted correctly

2. **Test overlap constraint:**
   - Create two rate cards with same combo + same SO line + overlapping dates → should FAIL
   - Create two rate cards with same combo + different SO lines + overlapping dates → should PASS

3. **Test immutability:**
   - Lock a rate card
   - Try to change SO fields → should FAIL
   - Try to change notes → should PASS

4. **Test UI filtering:**
   - Use "Linked to Sales Order" filter → verify only SO-linked cards show
   - Group by Sales Order → verify grouping works

---

### 🔮 Future Enhancements (Not in This Version)

- Smart button on SO showing linked rate cards
- Smart button on rate card showing linked timesheets
- Bulk rate card creation from SO lines
- Rate card templates based on SO products

---

### 📚 Updated Documentation

- README.md - Updated with SO integration examples
- GUIDANCE.md - Updated business logic and patterns

---

### 🐛 Known Issues

None reported.

---

### 👥 Contributors

- Implementation: Claude Code AI Assistant
- Review: [Your team]

---

## Version 1.0.0 (2026-01-27)

### Initial Release

- Core rate card model with multi-dimensional matching
- Deterministic resolution service (project-specific > client-wide)
- Effective dating with overlap prevention
- Governance states (draft, locked, invoiced_locked)
- Immutability rules enforcement
- Multi-company support
- Basic UI (tree, form, search views)
- Comprehensive documentation

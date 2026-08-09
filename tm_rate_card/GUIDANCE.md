# tm_rate_card Module - Developer Guidance

## Module Purpose

The `tm_rate_card` module serves as the **single source of truth** for Time & Materials (T&M) pricing in the Odoo ERP system. It provides a deterministic rate resolution engine with governance controls to ensure pricing integrity from timesheet entry through invoicing.

**Scope:** This module handles ONLY rate card master data and resolution logic. It does NOT handle timesheet validation, invoicing, or external system integration.

---

## Dependencies worth knowing (v1.14.11)

`sale_timesheet` is declared explicitly since v1.14.11. Three fields this module
touches on `account.analytic.line` are defined there, not in `sale`
(`sale_timesheet/models/account.py:41-47`):

| field | used by |
|---|---|
| `timesheet_invoice_id` | the invoiced lock in `write()` (`models/account_analytic_line.py:221`) |
| `so_line` | client resolution and SO-line assignment |
| `is_so_line_edited` | SO-line assignment |

Up to v1.14.10 the dependency was missing and everything worked anyway, because
`sale_timesheet` is `auto_install` and therefore present on any database that has
`sale` and `hr_timesheet`. That is luck, not a contract: on an install without it the
module would load and then fail at runtime with `AttributeError: 'account.analytic.line'
object has no attribute 'timesheet_invoice_id'`. The same trap already cost a debugging
session in `jito_timesheet_rounding`, which hit exactly that error in its tests.

---

## Architecture Overview

### Design Pattern
**Single Flat Model** - One model (`tm.rate.card.entry`) containing all dimensions, pricing, effective dating, and governance fields.

**Why this pattern?**
- Simple, direct mapping to business requirements
- Easy to query and maintain
- Aligns with Odoo 17 patterns (similar to `hr_contract`, `product_supplierinfo`)
- Single table for deterministic resolution = better performance

---

## Main Models

### `tm.rate.card.entry`

**Purpose:** Defines a billable rate for a specific combination of dimensions within an effective date range.

**Unique Combination (no overlaps allowed):**
- `company_id`
- `client_id`
- `service_product_id`
- `employee_id`
- `currency_id`
- `project_id` (NULL treated as distinct value from any project ID)

**State Progression:**
```
draft → locked → invoiced_locked
  ↑       ↓
  └───────┘ (unlock allowed only before invoicing)
```

**Key Methods:**
- `resolve_rate()` - Deterministic rate matching service
- `explain_resolution()` - Debugging helper
- `action_lock()` - Transition to locked state
- `action_invoiced_lock()` - Transition to invoiced state
- `action_unlock()` - Admin override (draft to locked only)

---

## Business Logic

### 1. Deterministic Rate Resolution

**Priority Rules:**
1. **Project-specific** rate (if project provided and matching entry exists)
2. **Client-wide** rate (if project_id = False)

**Matching Logic:**
```python
# Pseudo-code
if project:
    search for: (company, client, product, employee, currency, project, date range)
    if found: return entry

# Fallback:
search for: (company, client, product, employee, currency, project=False, date range)
if found: return entry
else: raise ValidationError("No match")
```

**Date Range Matching:**
- Inclusive: `date_start <= query_date AND (date_end >= query_date OR date_end IS NULL)`
- Open-ended dates supported (date_end = False means "forever")

**Error Handling:**
- No match → ValidationError with clear message
- Multiple matches → ValidationError (data integrity error, should never happen due to constraints)

### 2. Overlap Prevention

**Constraint:** `_check_no_overlap()`

**Logic:**
- For each active entry, search for other active entries with:
  - Same unique combination (company, client, product, employee, currency, project)
  - Overlapping date ranges

**Date Overlap Formula:**
```
Two ranges [A_start, A_end] and [B_start, B_end] overlap if:
  (B_start <= A_end OR A_end IS NULL) AND (B_end >= A_start OR B_end IS NULL)
```

**Implementation:** Uses `expression.AND()` to construct complex domain queries (pattern from `hr_contract.py:125-154`).

**Only active entries checked** - allows soft deletion without conflicts.

### 3. Governance & Immutability

**Write Override:** `write()` method enforces field immutability based on state.

**Immutability Rules:**

| State | Allowed Edits | Blocked Edits |
|-------|---------------|---------------|
| `draft` | All fields | None |
| `locked` | `notes`, `active` (with restrictions), `date_end` (only if currently NULL)** | All pricing-critical fields* |
| `invoiced_locked` | `notes` only | Everything else |

*Pricing-critical fields: `company_id`, `client_id`, `service_product_id`, `employee_id`, `currency_id`, `rate`, `date_start`, `date_end`, `project_id`

**Special case: `date_end` on locked entries**
- If a locked entry has `date_end = NULL`, it CAN be set to a date value
- Once set, `date_end` becomes immutable (cannot be changed again)
- This allows expiring rate cards that were initially created without an end date
- Prevents retroactive changes while allowing proper lifecycle management

**Deactivation Rules:**
- `draft` → can deactivate
- `locked` or `invoiced_locked` → **cannot deactivate** (use `date_end` instead to preserve history)

### 4. Timesheet Validation Workflow

**CRITICAL:** Rate cards are ONLY linked to timesheets during validation, not on creation or edit.

**Workflow Stages:**

```
Draft Timesheet → Validation → Rate Card Linking → RCE Auto-Lock → Validated Timesheet
```

**Stage Details:**

1. **Draft Timesheet Creation**
   - User creates/edits timesheet entry
   - No rate card is linked at this stage
   - Timesheet does NOT appear in RCE views
   - Can be edited freely

2. **Validation Trigger**
   - User clicks "Validate" on timesheet(s)
   - System calls `action_validate_timesheet()`
   - **CRITICAL:** Validation will FAIL if no matching RCE exists

3. **Rate Card Linking** (automatic during validation)
   - System searches for matching RCE using: company, client, employee, project, date
   - If found: Links timesheet to RCE, sets `tm_billing_rate` from RCE
   - If NOT found: Raises ValidationError with detailed message about what's missing
   - User-friendly error shows: client, project, employee, date needed for RCE creation

4. **RCE Auto-Lock** (automatic during validation)
   - After successful linking, system checks if RCE is in 'draft' state
   - If draft: Automatically transitions RCE to 'locked' state
   - Sets `locked_at` timestamp and `locked_by` user
   - RCE becomes immutable (pricing-critical fields cannot be changed)

5. **Validated Timesheet**
   - Timesheet marked as validated
   - NOW appears in RCE → Timesheets tab
   - Contributes to RCE statistics (hours, amount)
   - Cannot be edited without invalidation

**Visibility Rules:**

| Timesheet State | Appears in RCE Views | Has Rate Card Link | Can Edit |
|-----------------|----------------------|-------------------|----------|
| Draft | ❌ No | ❌ No | ✅ Yes |
| Validated | ✅ Yes | ✅ Yes | ❌ No* |

*Can be invalidated, then edited, then re-validated

**Error Handling:**

If validation fails due to missing RCE:
```
Cannot validate timesheet on 2026-01-29 for employee 'John Doe'.

No matching Rate Card Entry found for:
• Client: Acme Corp
• Project: Website Redesign
• Employee: John Doe
• Date: 2026-01-29

Please create a Rate Card Entry with these parameters before validating this timesheet.

Go to: Time & Materials → Rate Card Entries → Create
```

**Key Implementation Methods:**
- `action_validate_timesheet()` - Validation hook (account_analytic_line.py:159+)
- `_resolve_and_set_rate_card()` - Rate card resolution service (account_analytic_line.py:77+)
- `action_lock()` - Auto-lock RCE (tm_rate_card_entry.py:822+)

---

### 5. Adjusted Hours (`tm_adjusted_hours`) — v1.14.5+

**Purpose:** Allows PMs to adjust the hours used for billing without modifying the employee's logged hours.

**Field:** `account.analytic.line.tm_adjusted_hours` (stored Float, `digits='Hours'`)

**Precision — read before touching `digits` (v1.17.0):**

`'Hours'` is **not** a registered `decimal.precision` record, so
`precision_get()` falls back to **2 digits**
(`base/models/decimal_precision.py:34`) and the ORM rounds every write:
`Float.convert_to_column` and `convert_to_cache` both apply it. The DB column is
`numeric` with no scale constraint, so the rounding is entirely ORM-side.

That is **intended** since v1.17.0, and it is safe because of the module
`jito_timesheet_rounding`: tracked hours are snapped onto a 15/30-minute grid on
save, and `tm_adjusted_hours` is initialised from — and auto-synced to —
`unit_amount`. Every quarter hour (0.25, 0.5, 0.75, 1.0 …) is exact in two
decimals, so nothing is lost on the values this field actually carries.

> **History.** v1.14.8 changed this to `digits=False` because before the grid
> existed, arbitrary durations were logged and 0:20 / 0:40 / 1:10 were stored as
> 0.33 / 0.67 / 1.17. v1.17.0 reverted it together with the `[h]:mm` XLSX export
> in `jito_timesheet_rounding`, once the 15-minute grid removed the underlying
> problem.
>
> **Residual risk, accepted:** the grid applies to `unit_amount`, not to
> `tm_adjusted_hours`. A PM who types an Adjusted Hours value off the grid — 1:10
> as a billing correction — still gets `1.17` stored.

If you ever need full precision back, use `digits=False`, never a bare omission:
`digits=None` makes `Float.column_type` return `float8`
(`odoo/fields.py:1513-1519`), and Odoo then issues `ALTER COLUMN TYPE` and
rewrites the whole column. `False` and `'Hours'` both map to `numeric`, so
switching between those two never touches stored rows.

#### ⚠️ Known defect: Adjusted Hours does not follow a rounded duration

**Measured, accepted, and not fixed** — read this before investigating a report of
"we invoiced more hours than were logged".

`jito_timesheet_rounding` snaps `unit_amount` onto a 15/30-minute grid, and it does so
**after** `super().create()` (it has to: `project_id` and `company_id` are not resolved
in `vals` yet). But `create()` here copies `tm_adjusted_hours = vals['unit_amount']`
*before* that, so the copy is made from the **un-rounded** duration and `digits='Hours'`
immediately rounds it to 2 decimals. When the grid correction then writes the rounded
`unit_amount`, the auto-sync above compares the two and finds them different — so it
classifies the entry as manually adjusted and never syncs it again.

| typed | `unit_amount` (logged) | `tm_adjusted_hours` (invoiced) |
|---|---|---|
| 1:07 | 1.00 | **1.12** |
| 1:08 | 1.25 | **1.13** |
| 0:05 | 0.25 | **0.08** |

On-grid entries (1:15, 0:30 …) are unaffected: the copy is already exact in 2 decimals,
the values match, and the sync is a no-op.

Two ways out, if this is ever revisited:

- compare in the auto-sync at the precision the field is actually stored at
  (`float_compare(..., precision_digits=2)`), so `1.12` matches `round(1.11666, 2)` and
  the sync fires — a one-line change; or
- put `digits=False` back, which keeps the copy exact so the values compare equal.
  This is what v1.14.8–1.16.0 did, and it is why that version worked.

Neither was applied: v1.17.0 is a deliberate revert of the whole batch to the `main`
branch state. Correcting an affected entry is a PM retyping its Adjusted Hours —
existing entries are never touched in bulk (see below).

**Lifecycle:**
```
Employee logs 8h → unit_amount = 8.0
  → tm_adjusted_hours = 8.0  (auto-initialized via create())

Draft: Employee edits to 9h → unit_amount = 9.0
  → tm_adjusted_hours = 9.0  (auto-synced by write() override, only if not yet manually adjusted)

Validation → timesheet becomes validated

PM adjusts to 7.5h → tm_adjusted_hours = 7.5
  → unit_amount stays 8.0 (employee hours unaffected)
  → tm_billable_amount = 7.5 × rate (billing uses adjusted hours)

Invoice created → tm_adjusted_hours locked (write() raises ValidationError)
```

**Auto-sync Rules (write override):**
- `unit_amount` changes on a NON-validated timesheet where `tm_adjusted_hours == unit_amount` → syncs `tm_adjusted_hours` to match
- Matching is an exact `==` (restored in v1.17.0 with `digits='Hours'`). `unit_amount` is `float8` and `tm_adjusted_hours` is `numeric` rounded to 2 decimals, so the two agree exactly only when the duration is representable in 2 decimals — which every 15/30-minute grid value is. An **off-grid legacy row** (`unit_amount` 1.1666…, adjusted 1.17) compares unequal and is therefore classified as manually adjusted, so it stops following the logged hours for good
- Context flag `_syncing_adjusted_hours=True` prevents recursion
- Once PM sets a custom `tm_adjusted_hours` (≠ unit_amount), it will NOT be overwritten by future unit_amount changes on draft timesheets

**Known limitation:** "manually adjusted" is inferred by comparing values, not recorded
explicitly. A PM who adjusts hours back to exactly the logged value re-enables auto-sync.
Making this explicit needs a new boolean field and a decision about what its default means
for rows that already carry adjustments.

**Existing rows are never repaired in bulk — deliberate:**

Off-grid rows (0:20 stored as `0.33`, 1:10 as `1.17`) are left exactly as they are, and
**no repair tool exists**. A "Re-sync Adjusted Hours" button shipped briefly in v1.14.9
and was removed under the business rule that existing entries must not be modified — not
automatically, not in bulk, not by an admin action. Do not reintroduce one without that
decision being revisited. The same rule governs `jito_timesheet_rounding`, which rounds
on save only and never sweeps stored rows.

Two consequences to know before debugging a report of "wrong hours":

1. Such a row never self-heals. Its Adjusted Hours no longer match `unit_amount`, so the
   auto-sync above classifies it as manually adjusted and stops following the logged
   hours for good. That is indistinguishable, in the data, from a genuine PM adjustment.
2. Sums over a mixed population are off. Three 0:40 entries total `0.99` instead of
   `2.0`. Rows written by the raw SQL in `hooks.py` bypass the ORM and so kept full
   precision, as did rows written between v1.14.8 and v1.17.0; those populations coexist
   in every existing database.

The supported way to correct an individual row is for a PM to retype the Adjusted
Hours on that entry.

**Immutability:**
- Locked once timesheet is invoiced (`timesheet_invoice_id` non-null & not cancelled)
- Server-side: `write()` raises `ValidationError`
- Client-side: `readonly="is_invoiced"` applied via `tm_billing_control` view patch

**Downstream Impact:**
- `tm_billable_amount = tm_adjusted_hours × tm_billing_rate` (was unit_amount)
- `tm_rate_card_entry.timesheet_hours` uses `tm_adjusted_hours` (was unit_amount)
- `tm_billing_run` grouping uses `tm_adjusted_hours` for hours accumulation
- `tm_billing_run_line_timesheet.hours` related to `tm_adjusted_hours`
- Invoice line quantity uses billing line hours (cascade from above)

**Migration (post_init_hook):**
- On module upgrade: `UPDATE account_analytic_line SET tm_adjusted_hours = unit_amount WHERE tm_adjusted_hours IS NULL`

---

### 6. Billable Amount totals in timesheet lists — v1.15.0+ (single header bar since v1.18.0)

**Fields:** `account.analytic.line.tm_billable_currency_id` (Many2one, computed, **not** stored)

`= tm_billing_currency_id or company_id.currency_id`.

**Why it exists.** The list footer is computed client side by `ListRenderer.aggregates`
(`web/views/list/list_renderer.js:667-755`). For a monetary column it:

1. resolves the currency field from the column `options`, then the field definition,
   then `currency_id`;
2. shows `—` ("No currency provided") if that field is **not part of the view**, before
   even looking at `sum=`;
3. shows `—` ("Different currencies cannot be aggregated") if the loaded rows do not all
   share the same currency.

`tm_billable_amount` uses `tm_billing_currency_id`, which is empty on every timesheet
without a rate card, so both traps fired: the column was not in the arch (2), and rows
with and without a rate card looked multi-currency (3). Lines with no rate card are worth
0.00, so giving them the company currency changes no total — it only stops them from
suppressing it. Real currency differences (e.g. USD vs EUR rate cards) still produce `—`,
which is correct.

`tm_billable_amount.currency_field` was deliberately **left** on `tm_billing_currency_id`;
the fallback is applied per view through
`options="{'currency_field': 'tm_billable_currency_id'}"`, which `MonetaryField` honours
too (`monetary_field.js:43-47, 105`). Other views keep their previous behaviour.

**Totals in the header.** `static/src/js/timesheet_totals_renderer.js` registers the view
class `tm_timesheet_totals_list` (a `ListRenderer` subclass), attached to
`hr_timesheet.timesheet_view_tree_user` — the tree used by *Project → Timesheets* and by a
few neighbouring timesheet actions (`sale_timesheet`, `industry_fsm`,
`project_timesheet_forecast`, `timesheet_grid`). It repeats the aggregates as **one row**
inside `<thead>`; the standard footer is left untouched.

**Why the header and not a sticky footer** (v1.15.0 did the latter). `position: sticky`
resolves against the element's own place in the flow, and `<tfoot>` always follows
`<tbody>`: pinning it with `top` engages only once the whole table has scrolled past, so
totals can never sit *above* the rows that way. Core already makes the header sticky as a
whole element (`web/views/list/list_renderer.scss:16-19`), so a row added inside `<thead>`
is pinned for free — this module carries no positioning code at all now.

Two constraints that keep it from breaking:

- **the cells must stay `<td>`.** Every core lookup into the header goes through
  `thead th` (`list_renderer.js:180, 347, 408, 428, 2150` — sorting, resizing, column width
  computation). `<th>` would enrol the totals row in all of them;
- **the leading and trailing cells must mirror the footer row**
  (`list_renderer.xml:86, 94-95`). Without them the columns drift whenever selectors, the
  form-view opener or the optional-fields dropdown are present.

**Three things the row needs that core does not give it** (all in
`static/src/scss/timesheet_totals.scss`, and each one is a bug if dropped):

1. **`text-align: right` on its own `.o_list_number` cells.** Core right-aligns figures
   only under `tbody > tr > td` and under `tfoot` (`list_renderer.scss:91, 143`). A row in
   `<thead>` matches neither, so its totals sit left while every value below sits right —
   the columns read as misaligned. Fixed in v1.18.0; this is what "the bar is crooked"
   meant.
2. **A background of its own.** `<thead>` paints `--ListRenderer-thead-bg-color` behind the
   whole block, so a transparent row would sit flush with the grey column titles and read
   as one more header line. The bar uses `$o-view-background-color` — the colour of the
   data rows — plus a border on **both** edges: core zeroes the table group border
   (`> :not(:first-child) { border-top-width: 0 }`), so without the bottom line the bar
   would bleed into the first record.

   Do **not** reach for `$o-list-footer-bg-color` here. It is `transparent`
   (`web/static/src/scss/primary_variables.scss:134`, and again in `web_enterprise:43`) —
   the standard footer is bold text on the view background, not a filled plate — so using
   it compiles to no background at all.
3. **`display: none` during `.o_list_computing_widths`.** `freezeColumnWidths()`
   (`list_renderer.js:341-374`) measures the table with `table-layout: auto` and flags that
   pass with this class. Anything rendered during it takes part in the natural width
   computation, so the bar would push the columns around. Hiding it keeps the widths coming
   from the real header and the data rows only.

**The label is not cosmetic.** An ungrouped list aggregates only the records it loaded
(`dynamic_record_list.js` issues no `read_group`; the page limit is 80), so with 700
timesheets the bar shows the page, not the search result — and a bare number is easily
read as the total for the whole filter. So the row labels itself: `Totals`, or
`Totals · 80 of 700` when the page does not cover everything, with the full sentence in a
tooltip. Grouped lists are different — their aggregates come from `read_group` — so there
the label stays plain, as it does when a selection is active.

The label **spans** the columns before the first total (`totalsLabelColspan`) rather than
sitting in the first cell. In a timesheet list that cell is Date, far too narrow for the
text, and since the width pass runs on `table-layout: auto`, a long string in one cell
would widen that column. Keep the label short for the same reason — the tooltip is where
the prose belongs. `colspan` of `0` (the first column is itself a total) drops the label,
and `hasTotals` drops the whole row when no displayed column carries an aggregate.

---

## Views

### Tree View (`view_tm_rate_card_entry_tree`)
- Shows all key dimensions, pricing, dates, state
- Color-coded by state: draft (blue), locked (orange), invoiced (red)
- Muted when inactive
- Sample data enabled for demo

### Form View (`view_tm_rate_card_entry_form`)
- Header: statusbar + action buttons (Lock, Unlock)
- Grouped sections: Dimensions, Pricing, Effective Period, Governance
- Notebook tab: Notes
- Chatter: activity tracking, messages
- Archived ribbon when inactive

### Search View (`view_tm_rate_card_entry_search`)
- Search by: client, project, employee, service product, company
- Filters: active/archived, draft/locked/invoiced, current/future/expired, client-wide/project-specific
- Group by: client, project, product, employee, company, state, currency

### Timesheet Tree View (`view_tm_rate_card_timesheet_tree`)
- Embedded in Rate Card Entry form view
- Shows timesheets linked to this rate card entry
- **Key Features:**
  - Date, employee, project, task, description
  - Hours with sum total
  - Billing rate and billable amount (with sum)
  - Currency display (optional column)
  - **Validation status** - Shows whether timesheet is draft or validated
  - Cost display (optional, hidden by default)
- **Visual Indicators:**
  - Validated timesheets appear muted (greyed out)
  - Validation status uses badge widget with color coding
- Read-only view (no create/edit/delete from this context)

### Draft Timesheet Preview (`view_tm_rate_card_draft_timesheet_tree`)
- **NEW in v1.12.0** - Preview unvalidated timesheets that match this RCE
- Shows draft timesheets that WILL link to this RCE when validated
- **Purpose:** Forecasting, pre-validation checking, workload planning
- **Matching Logic:**
  - Draft only (validated=False)
  - Same employee, company, client (via project)
  - Within date range (if specified)
  - Project-specific or client-wide matching
- **Statistics:**
  - `draft_timesheet_count` - Number of matching draft timesheets
  - `draft_timesheet_hours` - Total hours from matching drafts
  - `draft_timesheet_amount` - Estimated billable amount (hours × rate)
- **Visual Indicators:**
  - Orange/warning decoration on all rows
  - Warning banner explains preview mode
  - Information box explains validation behavior
- **Updates:** Real-time as draft timesheets created/edited/deleted/validated
- **Use Cases:**
  - Revenue forecasting before validation
  - Verify timesheets will link to correct RCE
  - Test new rate card configuration
  - Plan validation schedules

---

## Security

### Groups
- `group_tm_rate_card_viewer` - Read-only access
- `group_tm_rate_card_manager` - Full CRUD (subject to governance rules)

### Record Rules
- Multi-company rule: `[('company_id', 'in', company_ids)]`
- Users only see entries in companies they have access to

### Access Rights
| Group | Model | Read | Write | Create | Unlink |
|-------|-------|------|-------|--------|--------|
| Viewer | tm.rate.card.entry | ✅ | ❌ | ❌ | ❌ |
| Manager | tm.rate.card.entry | ✅ | ✅ | ✅ | ✅ |

**Note:** Even Managers cannot bypass governance rules (enforced in Python `write()` method).

---

## Important Patterns & Constraints

### 1. Date Range Handling
**Pattern:** Similar to `hr_contract` (Odoo 17 Enterprise)

**Key Points:**
- Use `expression.AND()` for complex domain queries
- Handle open-ended dates (date_end = False)
- Inclusive date ranges
- Index date fields for performance

**Reference:** `odoo17_enterprise/odoo/addons/hr_contract/models/hr_contract.py:125-154`

### 2. State Management
**Pattern:** Similar to `hr_payslip` (Odoo 17 Enterprise)

**Key Points:**
- State field: `readonly=True`, `tracking=True`
- Transitions controlled via action methods, not direct writes
- `write()` override enforces field-level immutability

**Reference:** `odoo17_enterprise/odoo/addons/hr_payslip/models/hr_payslip.py:67-78`

### 3. Multi-Company
**Pattern:** Standard Odoo multi-company

**Key Points:**
- `_check_company_auto = True` - automatic validation
- Record rule with `company_ids` domain
- Default company: `lambda self: self.env.company`

**Reference:** `odoo17_enterprise/odoo/addons/hr_payroll/security/hr_payroll_security.xml:99-103`

### 4. Monetary Fields
**Pattern:** Similar to `hr_contract` (Odoo 17 Enterprise)

**Key Points:**
- `rate = fields.Monetary(currency_field='currency_id', digits=(16, 2))`
- `currency_id` defaults to company currency
- Use `widget="monetary"` in views

**Reference:** `odoo17_enterprise/odoo/addons/hr_contract/models/hr_contract.py:41-42, 69`

---

## Integration Guidelines

### Timesheet Validation Integration (IMPLEMENTED)

This module now includes full timesheet validation integration via the `account_analytic_line` model extension.

**Implementation:**
- Module: `tm_rate_card/models/account_analytic_line.py`
- Hook: `action_validate_timesheet()` override
- Auto-linking: Yes (on validation only)
- Auto-locking: Yes (RCE auto-locks when timesheets validated)
- Error enforcement: Yes (validation fails if no matching RCE)

**Key Methods:**
```python
# Override validation workflow
def action_validate_timesheet(self):
    # 1. Link rate cards (REQUIRED - raises error if not found)
    self._resolve_and_set_rate_card(raise_on_error=True)

    # 2. Call parent validation
    result = super().action_validate_timesheet()

    # 3. Auto-lock draft RCEs
    self.mapped('tm_rate_card_entry_id').filtered(
        lambda r: r.state == 'draft'
    ).action_lock()

    return result
```

**Fields Added to Timesheets:**
- `tm_rate_card_entry_id` - Link to rate card used
- `tm_billing_rate` - Billing rate from RCE
- `tm_billable_amount` - Computed (hours × rate)

**Why This Design?**
- ✅ Preserves exact rate used (even if rate card changes later)
- ✅ Enables traceability for invoicing
- ✅ Automatic locking prevents retroactive changes
- ✅ Validation enforcement ensures billing integrity
- ✅ Only validated timesheets appear in RCE views

### For Future Invoicing Module

**Requirements:**
1. Read rate card references from timesheet lines:
   ```python
   rate_entries = invoice.timesheet_ids.mapped('rate_card_entry_id')
   ```
2. After invoice confirmation, invoiced-lock rate cards:
   ```python
   rate_entries.action_invoiced_lock()
   ```

**Why invoiced locking?**
- Ensures rate cannot change after invoice sent to customer
- Maintains invoice integrity for audit trails
- Prevents retroactive changes that would cause discrepancies

---

## Common Pitfalls & Solutions

### Pitfall 1: Trying to create overlapping entries
**Error:** `ValidationError: Overlapping rate card entry detected`

**Solution:**
- Use date filters to check existing entries first
- Close old entries (set `date_end`) before creating new ones
- Use `active=False` for draft entries if not yet used

### Pitfall 2: Editing locked entries
**Error:** `ValidationError: Cannot modify ... - entry is locked`

**Solution:**
- For corrections: Use `action_unlock()` button (Manager group)
- For rate changes: Create new entry with future `date_start`
- Never force-unlock invoiced entries

### Pitfall 3: No matching rate found
**Error:** `ValidationError: No matching rate card entry found`

**Root causes:**
- Rate card doesn't exist for that combination
- Date outside effective range
- Entry is inactive
- Project-specific rate expected but only client-wide exists (or vice versa)

**Solution:**
- Create missing rate card entry
- Check date ranges (use "Current" filter to see active rates)
- Verify `active=True`
- Use `explain_resolution()` for debugging

### Pitfall 4: Deactivation blocked
**Error:** `ValidationError: Cannot deactivate entry in state 'locked'`

**Solution:**
- Set `date_end` to past date instead of deactivating
- Deactivation only allowed for `draft` entries

---

## Testing Recommendations

While unit tests are not included in this module, here are recommended test scenarios for manual testing or future test development:

### 1. Overlap Constraint Tests
- Create two entries with same combo + overlapping dates → should fail
- Create two entries with same combo + adjacent dates (day-by-day) → should pass
- Create entry with open-ended date, then overlapping entry → should fail
- Create entry with project=NULL, then project=123 (same dates) → should pass (different combo)
- Deactivate entry, create overlapping with same combo → should pass (only active checked)

### 2. Resolution Service Tests
- Query with matching project-specific entry → should return project entry
- Query with no project-specific but has client-wide → should return client entry
- Query with both project and client-wide → should return project (priority)
- Query with no match → should raise ValidationError
- Query on exact date boundaries (date_start, date_end) → should include boundaries

### 3. Governance Tests
- Edit draft entry (all fields) → should succeed
- Edit locked entry (pricing fields) → should fail
- Edit locked entry (notes) → should succeed
- Edit invoiced entry (notes) → should succeed
- Edit invoiced entry (anything else) → should fail
- Deactivate draft → should succeed
- Deactivate locked → should fail

### 4. Multi-Company Tests
- User in Company A → should only see Company A entries
- User in Companies A+B → should see both A and B entries
- User in Company A tries to create entry in Company B → should fail (if not authorized)

---

## Performance Notes

### Indexed Fields
- `date_start` (for date range queries)
- `date_end` (for date range queries)
- `company_id` (for multi-company filtering)
- `client_id` (for frequent filtering)
- `service_product_id` (for frequent filtering)
- `employee_id` (for frequent filtering)
- `project_id` (for frequent filtering)
- `state` (for state-based queries)

### Optimization Opportunities
- **Caching:** Consider adding `@ormcache` to `resolve_rate()` if called very frequently
- **Batch resolution:** If resolving rates for multiple timesheet lines, consider batch query patterns
- **Constraint performance:** Overlap constraint only checks active entries (reduces query size)

---

## Troubleshooting Tips

### Enable Developer Mode
Settings > Activate Developer Mode

**Useful for:**
- Viewing technical field names
- Checking domain filters
- Inspecting SQL queries
- Accessing Python debugger

### Check Logs
**Linux:** `tail -f /var/log/odoo/odoo-server.log`

**Docker:** `docker logs -f <container_name>`

**Look for:**
- ValidationError messages (will show in logs with full traceback)
- SQL queries (if `--log-sql` enabled)
- Domain filters (if `--log-level=debug`)

### Common Debugging Commands

```python
# In Odoo shell or debug mode

# Check if rate exists
self.env['tm.rate.card.entry'].search([
    ('client_id', '=', client.id),
    ('employee_id', '=', employee.id),
    ('date_start', '<=', '2026-01-27'),
    '|', ('date_end', '>=', '2026-01-27'), ('date_end', '=', False),
])

# Explain resolution
result = self.env['tm.rate.card.entry'].explain_resolution(
    company, client, product, employee, currency, date, project
)
print(result)

# Check overlaps (should return empty if no overlaps)
self.env['tm.rate.card.entry'].search([
    ('company_id', '=', 1),
    ('client_id', '=', 10),
    # ... add other dimensions
    ('date_start', '<=', '2026-12-31'),
    '|', ('date_end', '>=', '2026-01-01'), ('date_end', '=', False),
])
```

---

## Module Maintenance

### Version Increment
Per project guidelines, when updating this module, increment version in `__manifest__.py`:
```python
'version': '1.1.0',  # Increment for updates
```

### Data Migration
If you change model structure (add/remove/rename fields):
1. Create migration script: `migrations/1.1.0/pre-migrate.py` or `post-migrate.py`
2. Handle existing data carefully (especially locked/invoiced entries)
3. Test on staging environment first

### Backward Compatibility
- **NEVER** remove public API methods (`resolve_rate`, `explain_resolution`, `action_*`)
- **NEVER** change method signatures (add optional params only)
- **NEVER** change state values (would break existing data)
- If deprecating functionality, add warnings in docstrings and logs

---

## Summary

**What this module does:**
- Stores T&M rate card master data
- Resolves rates deterministically with project-specific priority
- Prevents overlapping effective date ranges
- Enforces immutability based on usage (timesheets, invoices)
- Provides multi-company support

**What this module does NOT do:**
- Timesheet validation (future module)
- Invoicing (future module)
- Sage integration (future module)
- Automatic rate card creation
- Rate card templates or bulk operations (can be added later)

**Key takeaway:** This is a **foundation module** - other modules will depend on it for pricing authority. Keep it stable, well-tested, and backward-compatible.

---

## Further Reading

**Odoo 17 Documentation:**
- [ORM API](https://www.odoo.com/documentation/17.0/developer/reference/backend/orm.html)
- [Views](https://www.odoo.com/documentation/17.0/developer/reference/backend/views.html)
- [Security](https://www.odoo.com/documentation/17.0/developer/reference/backend/security.html)

**Reference Implementations (in Odoo 17 Enterprise source):**
- Date ranges: `odoo/addons/hr_contract/models/hr_contract.py`
- State management: `odoo/addons/hr_payslip/models/hr_payslip.py`
- Deterministic matching: `odoo/addons/product/models/product_pricelist.py`
- Multi-company: `odoo/addons/hr_payroll/security/hr_payroll_security.xml`

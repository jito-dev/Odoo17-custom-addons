# Billing Control Module - Technical Documentation

**Module Name:** `tm_billing_control`
**Version:** 1.10.0
**Author:** JITO LTD
**Dependencies:** `tm_rate_card`, `sale_timesheet`, `timesheet_grid`

---

## Recent Updates

### v1.10.10 (Bug Fixes: 0h Button, Auto-Preview, Dashboard Auto-Refresh)

**"Disable 0h Tracks" button in timesheet management form (Issue 2):**
- Added `action_exclude_zero_hour_timesheets()` on `tm.billing.run.line`: excludes all timesheet links with 0 adjusted hours from invoicing in one click.
- Button "Disable 0h Tracks" (fa-ban, btn-warning) added to `view_tm_billing_run_line_timesheet_form`, hidden when billing line is readonly.

**Auto-compute preview on Billing Run creation (Issue 4):**
- Extracted core preview line creation logic into `_create_preview_lines(timesheets)` internal method.
- `action_preview()` refactored to call `_create_preview_lines()` for code reuse.
- `create()` override now silently auto-previews after creation; errors are caught and suppressed so billing run creation never fails.
- When billing run is created with matching timesheets, it opens in `preview` state with lines already populated.

**Dashboard auto-refresh on open (Issue 5):**
- Dashboard `create()` now wraps `_generate_dashboard_lines()` in try/except to prevent dashboard opening from failing due to data generation errors. Dashboard was already auto-generating on create; the try/except makes it more robust.

---

### v1.10.6 (Dashboard: Smart "Create Billing Run" wizard)
**New wizard `tm.billing.run.create.wizard` launched from Dashboard:**
- Button "Create Billing Run for This Period" on Dashboard now opens a wizard (was a direct form)
- Wizard pre-fills `date_start` / `date_end` from the dashboard period
- **Opportunities table**: HTML table showing all available (client, currency) combinations with timesheet count, hours spent, adjusted hours, and estimated billable amount — only shows combinations that have validated, uninvoiced, rate-card-locked timesheets in the period
- **Client dropdown**: filtered to only clients with available timesheets in the period (`available_client_ids` computed M2M used for domain)
- **Currency dropdown**: dynamically filtered to currencies available for the selected client (`available_currency_ids` computed M2M, depends on `client_id`)
- **Live preview stats**: shows timesheet count, hours spent, adjusted hours, estimated amount for the selected (client, currency) combination; hidden until both are selected
- **Options**: Group by Project, Group by Month (passed to the billing run)
- **"Create Billing Run" button**: visible only when preview_ready (timesheets exist); creates `tm.billing.run` and navigates to it
- Security ACL: viewer (read) and manager (full CRUD) added to `ir.model.access.csv`
- `action_create_billing_run_wizard()` on `tm.billing.dashboard` creates the wizard and opens it via `target: new`
- Old `action_create_billing_run` (direct form open) retained for potential direct use

### v1.10.5 (Dashboard: Adjusted Hours metrics)
**Billing Dashboard now shows Adjusted Hours alongside Hours Spent:**
- `TmBillingDashboardLine` model: added 5 new Float fields — `validated_adjusted_hours`, `invoiced_adjusted_hours`, `paid_adjusted_hours`, `to_invoice_adjusted_hours`, `total_adjusted_hours`
- `_group_timesheets_with_metrics()`: accumulates `ts.tm_adjusted_hours` into `*_adjusted_hours` keys alongside existing `ts.unit_amount` keys
- `_generate_dashboard_lines()`: passes all 4 adjusted hours values to `DashboardLine.create()`
- `TmBillingDashboard` summary: added 4 new total fields (`total_validated_adjusted_hours`, etc.) with `_compute_totals()` and `@api.depends` updated
- **Form view summary**: Hours Breakdown now shows "X spent / Y adjusted" for each metric
- **Breakdown tree** (inline + standalone): added Adj. columns for each metric; "Spent" variants set to optional="hide" by default for less clutter
- **Pivot view**: all adjusted hours measures added with "(Adj.)" label suffix
- **Graph view**: shows Validated (Spent) + Validated (Adj.) + Invoiced (Adj.) + To Invoice (Adj.)

### v1.10.4 (Export: Both Hours Spent & Adjusted Hours)
**CSV Export and Advanced Export now expose both hours columns:**
- CSV export (`action_export_csv`): headers now include "Hours Spent" (unit_amount) AND "Adjusted Hours" (tm_adjusted_hours) as separate columns
- Excel export (`_generate_excel_file`): same two-column treatment, column indices shifted accordingly
- Preview HTML (`_generate_preview_html`): table now shows both columns side-by-side
- Advanced Export tree view (`view_account_analytic_line_export_tree`): added `tm_adjusted_hours` as optional column with "Total Adjusted Hours" sum, alongside existing `unit_amount` / "Total Hours Spent"
- `_get_export_data()`: `amount` now uses `tm_billable_amount` (computed from adjusted hours) instead of raw `unit_amount × rate`
- Data key `hours_spent` = logged hours; `hours` = adjusted billing hours

### v1.10.3 (Adjusted Hours Support)
**Billing calculations now use `tm_adjusted_hours` instead of `unit_amount`:**
- `tm_billing_run_line_timesheet.hours` related field changed from `timesheet_id.unit_amount` → `timesheet_id.tm_adjusted_hours`
- `_group_timesheets_for_preview()` now accumulates `ts.tm_adjusted_hours` instead of `ts.unit_amount`
- This allows PMs to adjust billing hours without modifying employee's logged hours
- `tm_adjusted_hours` is defined in `tm_rate_card` module (`account.analytic.line`)
- View patch added to make `tm_adjusted_hours` readonly when `is_invoiced = True`
- Invoice quantity still derived from billing line `hours` field (cascade correct)

### v1.10.0 (Timesheet Export)
**Export Timesheets to Excel/CSV:**
- 📊 **NEW**: Export billing run timesheets to Excel (.xlsx) and CSV (.csv) formats
- Three-step wizard workflow: Choose formats → Preview data → Download files
- Excel export includes:
  - Professional formatting with headers and column widths
  - Grouping by project and employee with subtotals
  - Grand totals at the bottom
  - Frozen header row for easy scrolling
- CSV export for importing into other systems
- Detailed timesheet breakdown with 18 columns:
  - Billing run info (reference, period, client)
  - Timesheet details (project, employee, date, task, description, hours, rate, amount)
  - Product/service and sales order linkage
  - Inclusion status (Yes/No)
  - Invoice information (number, state)
- Export available in preview, invoiced, and closed states
- Generates attachments linked to billing run for audit trail
- Preview shows first 50 rows before generating full export
- File naming: `Billing_Run_{reference}_{client}_{date}.xlsx/csv`
- Use cases:
  - Client review and billing transparency
  - Internal audits and reporting
  - Invoice backup documentation
  - Historical analysis and archiving

### v1.9.0 (Enhanced Dashboard Metrics)
**Comprehensive Billing Pipeline Visibility:**
- 📊 **NEW**: Expanded dashboard metrics for complete billing lifecycle tracking
- Added "Validated (Delivered) Hours" and "Validated (Delivered) Amount" - shows all delivered work
- Added "Paid Hours" and "Paid Amount" - shows fully paid timesheets
- Existing "Invoiced Hours/Amount" now tracks work with invoices (draft or posted)
- Existing "To Invoice Hours/Amount" continues to show uninvoiced work
- **Dashboard View Details (Pivot)** now displays all 6 metrics:
  - Validated (Delivered) Hours & Amount - baseline of all delivered work
  - Invoiced Hours & Amount - work that has been billed
  - Paid Hours & Amount - work that has been paid
  - To Invoice Hours & Amount - work ready to bill
- Updated tree, graph, and form views to show complete breakdown
- Summary section shows 4 metrics instead of 3 (added validated/delivered)
- Better insight into cash flow: Delivered → Invoiced → Paid pipeline
- Helps identify bottlenecks: how much is delivered but not invoiced, invoiced but not paid

### v1.8.3 (Immutability After Invoice Creation)
**Billing Line Freeze Enforcement:**
- 🔒 **IMPORTANT**: Billing lines are now completely frozen after invoice creation
- Added `is_readonly` computed field to billing lines and timesheet links
- All billing line fields are read-only after state transitions to 'invoiced' or 'closed'
- Timesheet inclusion/exclusion toggles are disabled after invoice creation
- Added write/unlink constraints to prevent any modifications via API or code
- Visual indicators (alert banners) show frozen status in forms
- Ensures data integrity: invoice data matches billing run snapshot permanently
- Exception: computed fields (hours, amount, counts) update automatically based on dependencies

### v1.8.2 (Database Schema Fix)
**Fixed Missing Database Columns:**
- 🔴 **CRITICAL FIX**: Added migration to create missing database columns for stored computed fields
- Fixed `column account_analytic_line.is_invoiced does not exist` error
- Added pre_init_hook to check and create `is_invoiced`, `invoice_state`, and `invoice_payment_state` columns
- Ensures proper database schema for timesheet status visibility features
- Resolves error when viewing Billing Line → Manage Timesheets on invoiced billing runs

### v1.8.0 (Timesheet Status Visibility)
**Enhanced Timesheet Views:**
- Added `is_invoiced` computed field to quickly identify invoiced timesheets
- Added `invoice_state` and `invoice_payment_state` related fields for full visibility
- Extended timesheet tree views to show validation, invoice, and payment status
- Status columns available in:
  - Project → Timesheets tab
  - Timesheets menu (HR Timesheet views)
  - Timesheet form view (billing status section)
- Color-coded badges for invoice states (draft/posted/cancelled)
- Color-coded badges for payment states (not paid/partial/paid)
- All status fields are optional columns (show/hide as needed)

### v1.7.1 (Project Resolution Improvement)
**Enhanced Project Display:**
- Project field now always populated from timesheet data (regardless of grouping setting)
- Invoice line descriptions now include project name in clean format: "Product - Employee - Project"
- Removed "Project:" prefix from invoice descriptions for better readability
- Example: "Software Development Hour - Danylo Kunyk - GeoX" instead of "Software Development Hour - Danylo Kunyk - Project: GeoX"

### v1.7.0 (Enhanced Visibility)
**Invoice Status Tracking:**
- Added `invoice_state` field (Draft, Posted, Cancelled) with color-coded badges
- Added `invoice_payment_state` field (Not Paid, Partial, Paid, In Payment) with status badges
- Invoice status now visible in billing run form view in dedicated "Invoice Status" section
- Invoice status and payment status available as optional columns in tree view
- Better visibility of invoice lifecycle without opening invoice form

### v1.6.1 (Critical Bug Fix)
**Fixed Excluded Timesheet Handling:**
- 🔴 **CRITICAL FIX**: Excluded timesheets are no longer marked as invoiced
- Excluded timesheets now remain available for future billing runs
- Only included timesheets are marked with `timesheet_invoice_id` and have rate cards locked
- Added validation to prevent invoice creation with no included timesheets
- Added `get_included_timesheets()` method to billing run lines

### v1.6.0

**Enhanced Timesheet Management:**
- Added inline timesheet management interface accessible from billing run form
- New "Manage Timesheets" button on each billing line opens a modal with include/exclude toggles
- Simplified form view for quick timesheet inclusion management
- Visual indication (greyed out) for excluded timesheets

**Improved UI/UX:**
- Fixed project field population - now only shows project when "Group by Project" is enabled
- Added success notification after "Compute Preview" with summary statistics
- Automatic form refresh after preview computation
- Better visual feedback throughout the workflow

---

## Overview

This module provides a controlled batch invoicing workflow for Time & Materials projects. It allows users to:
1. Create billing runs per (client, currency, period)
2. Preview billing grouped by multiple dimensions before invoice creation
3. Manage timesheet inclusion/exclusion at the line level
4. Generate invoices from immutable snapshots
5. Maintain complete audit trail from timesheets → billing run → invoice

---

## Main Models

### 1. `tm.billing.run`
**Purpose:** Master billing batch record

**Key Fields:**
- `reference` - Auto-generated sequence (e.g., BRN00001)
- `client_id` - Customer for this billing run
- `currency_id` - Currency (all timesheets must match)
- `date_start`, `date_end` - Period range (inclusive)
- `group_by_project` - Boolean: group billing lines by project
- `group_by_month` - Boolean: split billing lines by month
- `state` - Workflow: draft → preview → invoiced → closed
- `line_ids` - One2many to billing run lines
- `invoice_id` - Created invoice reference

**State Workflow:**
- **draft** → User creates billing run, selects client/period/options
- **preview** → System computes billing lines (grouped snapshots)
- **invoiced** → Invoice created, timesheets marked as invoiced
- **closed** → Finalized after invoice confirmation

**Key Methods:**
- `action_preview()` - Find timesheets, group, create preview lines
- `action_recompute()` - Delete and recreate preview (draft/preview only)
- `action_create_invoice()` - Generate invoice from preview lines
- `action_open_invoice()` - Navigate to created invoice
- `action_close()` - Finalize billing run (after invoice posted)

### 2. `tm.billing.run.line`
**Purpose:** Grouped billing preview line (immutable snapshot)

**Key Fields:**
- `billing_run_id` - Parent billing run
- `client_id`, `currency_id` - Client and currency
- `sale_order_line_id` - SO line (service bucket) from Rate Card Entry
- `product_id` - Service product from SO line
- `employee_id` - Employee who worked
- `rate` - Locked billing rate (from timesheet.tm_billing_rate)
- `project_id` - Optional project (only populated when group_by_project is enabled)
- `period_month` - Optional month (e.g., "2026-01") if grouped by month
- `hours` - Total hours (sum of included timesheets only)
- `amount` - Total billable amount (hours × rate from included timesheets only)
- `timesheet_line_ids` - One2many to tm.billing.run.line.timesheet (with include/exclude flags)
- `timesheet_ids` - Many2many computed from timesheet_line_ids (for compatibility)
- `invoice_line_id` - Created invoice line reference

**Key Methods:**
- `action_view_timesheets()` - Opens raw timesheets in tree view (read-only)
- `action_manage_timesheets()` - Opens simplified form in modal to manage timesheet inclusion/exclusion

**Grouping Key:**
```
(client, currency, SO line, employee, rate, project?, month?)
```

**Why Group by Rate?**
- Handles mid-period rate changes (e.g., employee gets raise on Jan 15)
- Ensures each invoice line has a single rate per employee

### 2a. `tm.billing.run.line.timesheet`
**Purpose:** Intermediary link between billing lines and timesheets with inclusion control

**Key Features:**
- Links individual timesheets to billing lines
- `included` boolean flag controls whether timesheet is included in invoice
- All timesheets included by default
- Users can exclude specific timesheets before invoice creation
- Totals (hours, amount) computed only from included timesheets
- Related fields for easy display (date, employee, project, task, hours, rate, amount)

### 3. `account.analytic.line` (Extension)
**Purpose:** Link timesheets to billing runs for traceability

**Added Fields:**
- `tm_billing_run_id` - Billing run that included this timesheet
- `tm_billing_run_line_ids` - Many2many to billing run lines

---

## Business Logic

### Timesheet Selection Criteria

When `action_preview()` is called, the system finds timesheets matching:

```python
domain = [
    ('validated', '=', True),              # Only validated timesheets
    '|',
        ('timesheet_invoice_id', '=', False),          # Not yet invoiced
        ('timesheet_invoice_id.state', '=', 'cancel'), # Or cancelled invoice
    ('tm_rate_card_entry_id', '!=', False),           # Has rate card
    ('tm_rate_card_entry_id.state', 'in', ['locked', 'invoiced_locked']),  # Locked rate
    ('company_id', '=', billing_run.company_id.id),
    ('date', '>=', billing_run.date_start),
    ('date', '<=', billing_run.date_end),
]
```

**Important:** We do NOT filter by `timesheet_invoice_type = 'billable_time'` because billability is determined by the Rate Card Entry, not direct SO linkage. Projects may not be attached to SO directly, only via Rate Card Module.

**Additional Filters (in code):**
- Client matches (via `project.partner_id` or `so_line.order_id.partner_id`)
- Currency matches (via `tm_rate_card_entry_id.currency_id`)

### Grouping Logic

Timesheets are grouped by:
1. **Client** (always)
2. **Currency** (always)
3. **SO Line** (service bucket from `tm_rate_card_entry_id.sale_order_line_id`)
4. **Employee** (always)
5. **Rate** (always - to handle mid-period changes)
6. **Project** (optional - if `group_by_project = True`)
7. **Month** (optional - if `group_by_month = True`)

Each unique combination creates one `tm.billing.run.line` record.

### Invoice Generation

When `action_create_invoice()` is called:

1. **Validate** - All timesheets still unbilled
2. **Create Invoice** - `account.move` with type `out_invoice`
3. **Create Invoice Lines** - One per `tm.billing.run.line`:
   ```python
   {
       'name': 'Product - Employee - Project - Period',
       'product_id': line.product_id.id,
       'quantity': line.hours,
       'price_unit': line.rate,
       'sale_line_ids': [(6, 0, [line.sale_order_line_id.id])],  # SO linkage
   }
   ```
4. **Link Timesheets** - Set `timesheet_invoice_id = invoice.id` (prevents double billing)
5. **Lock Rate Cards** - Transition to `invoiced_locked` state
6. **Update Billing Run** - Set `invoice_id`, state = `invoiced`

### Double-Billing Prevention

Uses standard Odoo mechanism:
- **timesheet_invoice_id** field links each timesheet to at most one invoice
- Selection domain excludes timesheets with `timesheet_invoice_id != False AND state != 'cancel'`
- Validation before invoice creation checks for already-invoiced timesheets

### Sales Order Linkage

**Critical:** Invoice lines link to correct SO line via:
```python
'sale_line_ids': [(6, 0, [line.sale_order_line_id.id])]
```

This ensures:
- SO `qty_delivered` counters remain accurate
- SO `qty_invoiced` counters update correctly
- Customer can see what was invoiced against which SO line

**SO Line Source:**
- Taken from `timesheet.tm_rate_card_entry_id.sale_order_line_id`
- NOT from `timesheet.so_line` (as per user clarification)
- Rate Card Entry is the authoritative source

### Timesheet Inclusion/Exclusion

**Purpose:** Allow selective invoicing of timesheets within a billing line.

**How It Works:**

1. **During Preview Creation** (action_preview):
   - All matching timesheets are added to billing lines
   - All timesheets are marked as `included = True` by default
   - Grouped into billing lines by standard dimensions

2. **User Management** (via Manage Timesheets modal):
   - Users can toggle `included` flag on individual timesheets
   - Excluded timesheets (included = False) appear greyed out
   - Totals (hours, amount) update automatically to show only included timesheets

3. **During Invoice Creation** (action_create_invoice):
   - **Only INCLUDED timesheets** are marked with `timesheet_invoice_id`
   - **Only INCLUDED timesheets** have rate cards locked to `invoiced_locked`
   - **EXCLUDED timesheets remain untouched** and available for future billing runs

4. **In Next Billing Run:**
   - Excluded timesheets from previous runs will appear again
   - They can be included in the new billing run
   - This allows deferring specific timesheets to later billing periods

**Important Behaviors:**

✅ **Included Timesheets:**
- Get linked to invoice via `timesheet_invoice_id`
- Rate cards locked to prevent changes
- Won't appear in future billing run previews

❌ **Excluded Timesheets:**
- Do NOT get linked to any invoice
- Rate cards remain in `locked` state (can still be adjusted)
- WILL appear in future billing runs (still unbilled)
- Can be re-selected and included in next period

**Use Cases:**
- Timesheet needs client approval before billing → Exclude for now, include next month
- Dispute about hours worked → Exclude disputed entries, invoice the rest
- Partial period billing → Include only specific days/weeks, defer others
- Project budget exceeded → Defer some hours to next billing cycle

---

## Security

### Groups
- **Billing Control Viewer** - Read-only access to billing runs
- **Billing Control Manager** - Full access (create, preview, invoice, close)

### Record Rules
- Multi-company: Users only see billing runs in their allowed companies
- Based on `billing_run.company_id`

### Access Control List (ACL)
```
tm.billing.run:
  - Viewer: read
  - Manager: read, write, create, unlink

tm.billing.run.line:
  - Viewer: read
  - Manager: read, write, create, unlink
```

---

## Immutability Rules

### Billing Run (`tm.billing.run`)
- **Draft** → All fields editable
- **Preview/Invoiced/Closed** → Core fields locked:
  - `client_id`, `currency_id`, `date_start`, `date_end`
  - `group_by_project`, `group_by_month`, `company_id`
- **Invoiced/Closed** → Cannot delete (archive instead)

### Billing Run Lines (`tm.billing.run.line`)
- Created during preview
- Immutable after creation (readonly in UI)
- Deleted only when parent billing run deleted or recomputed

---

## Integration Points

### With `tm_rate_card`
- Uses `tm_rate_card_entry_id` from timesheets
- Reads `sale_order_line_id` from rate card entry
- Reads `tm_billing_rate` from timesheet (locked from rate card)
- Calls `rate_card.action_invoiced_lock()` after invoice creation

### With `sale_timesheet`
- Uses `timesheet_invoice_id` for double-billing prevention
- Uses `timesheet_invoice_type` to filter billable timesheets
- Links invoice lines to SO lines via `sale_line_ids`

### With `timesheet_grid`
- Uses `validated` field to filter validated timesheets only

### With `account` (Invoicing)
- Creates `account.move` (invoice)
- Creates `account.move.line` (invoice lines)
- Links via `timesheet_invoice_id`

---

## Usage Workflow

### 1. Create Billing Run
```
User → Billing Control → Billing Runs → Create
  - Select Client: ABC Corp
  - Select Currency: USD
  - Set Period: 2026-01-01 to 2026-01-31
  - Enable "Group by Project" (optional)
  - Save → State: draft
```

### 2. Compute Preview
```
User → Click "Compute Preview"
  - System finds 120 validated timesheets
  - Groups into 15 billing lines
  - State → preview
  - User reviews billing lines
```

### 3. Recompute (if needed)
```
User → Click "Recompute Preview"
  - Deletes existing lines
  - Recomputes from latest timesheet data
  - Useful if new timesheets validated after initial preview
```

### 4. Create Invoice
```
User → Click "Create Invoice"
  - System creates account.move (Invoice INV/2026/0042)
  - Creates 15 invoice lines from billing lines
  - Links 120 timesheets to invoice
  - Locks 8 rate card entries to invoiced_locked
  - State → invoiced
  - Opens invoice form
```

### 5. Confirm Invoice
```
User → On invoice form → Click "Confirm"
  - Invoice posted
  - Timesheets now permanently linked
```

### 6. Close Billing Run
```
User → Back to billing run → Click "Close Billing Run"
  - Finalizes billing run
  - State → closed
  - Audit trail complete
```

---

## Key Patterns & Constraints

### 1. One Billing Run → One Invoice
- Current design: strict 1:1 relationship
- Future: Could extend to support multiple invoices per run (e.g., per currency)

### 2. Currency Handling
- Single currency per billing run
- Multiple currencies require separate billing runs
- Future: Could support multi-currency with currency grouping

### 3. Grouping Flexibility
- `group_by_project` - OFF: All timesheets grouped client-wide per employee/SO line
- `group_by_project` - ON: Separate line per project
- `group_by_month` - ON: Split lines by month within period
- Both can be combined

### 4. Rate Change Handling
- Automatic: Grouping by rate ensures mid-period changes create separate lines
- Example: Employee rate $40/h → $45/h on Jan 15
  - Result: Two invoice lines (one at $40/h, one at $45/h)

### 5. Service Bucket Concept
- Service Bucket = Sales Order Line from Rate Card Entry
- Represents collection of subservices (e.g., "Software Development Hour")
- Invoice lines show specific instance (e.g., "Software Dev Hour - John Doe")

---

## Error Handling

### Common Errors & Solutions

**"No billable timesheets found"**
- Check: Timesheets validated?
- Check: Rate cards locked?
- Check: Timesheets already invoiced?
- Check: Date range correct?

**"Some timesheets have already been invoiced"**
- Solution: Recompute preview to exclude already-invoiced timesheets

**"Cannot create invoice from draft state"**
- Solution: Click "Compute Preview" first

**"Cannot close billing run while invoice is still in draft state"**
- Solution: Go to invoice, click "Confirm" first

---

## Database Schema

### Key Relationships
```
tm_billing_run (1) ──< (many) tm_billing_run_line
                 │
                 └──> (1) account_move (invoice)

tm_billing_run_line (many) ──< >── (many) account_analytic_line (timesheets)
                     │
                     └──> (1) sale_order_line (service bucket)
                     └──> (1) account_move_line (invoice line)

account_analytic_line ──> (1) tm_rate_card_entry
                      └──> (1) account_move (via timesheet_invoice_id)
```

### Key Indexes
- `tm_billing_run`: `company_id`, `client_id`, `date_start`, `date_end`, `state`, `invoice_id`
- `tm_billing_run_line`: `billing_run_id`, `client_id`, `employee_id`, `product_id`, `sale_order_line_id`
- `account_analytic_line`: `tm_billing_run_id`

---

## Performance Considerations

- Timesheet selection uses indexed fields (`validated`, `date`, `company_id`)
- Grouping done in Python (not SQL) for flexibility
- Large billing runs (1000+ timesheets) may take 10-30 seconds for preview
- Invoice creation is fast (single SQL transaction)

---

## Future Enhancements

1. **Approval Workflow** - Add `pending_approval` state before invoice creation
2. **Multi-Invoice Support** - Support multiple invoices per billing run (per currency/client)
3. **Partial Invoicing** - Allow selecting specific billing lines to invoice
4. **Export to External Systems** - Export billing data before invoice creation
5. **Automated Scheduling** - Create billing runs automatically (e.g., end of month)
6. **Email Notifications** - Notify stakeholders when billing run closed

---

## Troubleshooting

### Timesheets Not Appearing in Preview
Check:
1. `validated = True`?
2. `timesheet_invoice_id = False` or `state = 'cancel'`?
3. `tm_rate_card_entry_id` exists and state in `['locked', 'invoiced_locked']`?
4. Date within billing run period?
5. Client matches (via project or SO line)?
6. Currency matches (via rate card entry)?

**Note:** We do NOT check `timesheet_invoice_type = 'billable_time'` because billability is determined by Rate Card Entry.

### Invoice Lines Not Linking to SO
Check:
1. `timesheet.tm_rate_card_entry_id.sale_order_line_id` exists?
2. SO line not archived/deleted?
3. Verify `invoice_line.sale_line_ids` populated correctly

### Rate Cards Not Locking
Check:
1. Invoice created successfully?
2. Rate card entry state was `locked` (not already `invoiced_locked`)?
3. Check rate card entry audit log

---

## Testing Checklist

- [ ] Create billing run (draft state)
- [ ] Compute preview with timesheets
- [ ] Recompute preview (lines recreated)
- [ ] Create invoice from preview
- [ ] Verify timesheets linked to invoice
- [ ] Verify rate cards locked to invoiced_locked
- [ ] Verify SO line linkage correct
- [ ] Confirm invoice
- [ ] Close billing run
- [ ] Test grouping options (by project, by month)
- [ ] Test multi-company access
- [ ] Test security (viewer vs manager)
- [ ] Test double-billing prevention (reuse same timesheets)
- [ ] Test mid-period rate changes (separate lines)

---

**Last Updated:** 2026-01-30
**Module Status:** ✅ Initial Implementation Complete

# Billing Control Module - Technical Documentation

**Module Name:** `tm_billing_control`
**Version:** 1.0.0
**Author:** JITO LTD
**Dependencies:** `tm_rate_card`, `sale_timesheet`, `timesheet_grid`

---

## Overview

This module provides a controlled batch invoicing workflow for Time & Materials projects. It allows users to:
1. Create billing runs per (client, currency, period)
2. Preview billing grouped by multiple dimensions before invoice creation
3. Generate invoices from immutable snapshots
4. Maintain complete audit trail from timesheets → billing run → invoice

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
- `project_id` - Optional project (if grouped by project)
- `period_month` - Optional month (e.g., "2026-01") if grouped by month
- `hours` - Total hours (sum of timesheets)
- `amount` - Total billable amount (hours × rate)
- `timesheet_ids` - Many2many link to included timesheets
- `invoice_line_id` - Created invoice line reference

**Grouping Key:**
```
(client, currency, SO line, employee, rate, project?, month?)
```

**Why Group by Rate?**
- Handles mid-period rate changes (e.g., employee gets raise on Jan 15)
- Ensures each invoice line has a single rate per employee

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

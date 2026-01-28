# Rate Card Management (Pricing Authority)

**Version:** 1.0.0
**Category:** Services/Project
**Author:** Your Company

---

## Overview

The **Rate Card Management** module is the **single source of truth** for Time & Materials (T&M) pricing in Odoo. It provides deterministic rate resolution, effective dating, governance controls, and immutability rules to ensure pricing integrity throughout the timesheet-to-invoice lifecycle.

This module handles **ONLY** the Rate Card master data and resolution logic. Timesheet validation, invoicing, and external system integration (e.g., Sage) are handled by separate modules.

---

## Key Features

### 1. **Multi-Dimensional Rate Matching**
Each rate card entry defines a billable rate for a specific combination of:
- **Company** (multi-company support)
- **Client** (customer)
- **Project** (optional - for project-specific rates)
- **Service Product** (e.g., "Dev Hour", "PM Hour")
- **Employee**
- **Currency**

### 2. **Effective Dating**
- **date_start**: When the rate becomes effective (inclusive)
- **date_end**: When the rate expires (inclusive) - leave blank for open-ended
- **Overlap prevention**: Constraints ensure no overlapping date ranges for the same combination

### 3. **Deterministic Rate Resolution**
The module provides a Python service `resolve_rate()` that deterministically selects the correct rate:

**Priority Rules:**
1. **Project-specific** rate (if project provided and match exists)
2. **Client-wide** rate (if no project-specific match)

**Example:**
```python
# In your custom module
rate_entry = self.env['tm.rate.card.entry'].resolve_rate(
    company=self.env.company,
    client=timesheet_line.project_id.partner_id,
    service_product=timesheet_line.product_id,
    employee=timesheet_line.employee_id,
    currency=self.env.company.currency_id,
    date=timesheet_line.date,
    project=timesheet_line.project_id,
)

billable_rate = rate_entry.rate
```

### 4. **Governance & Immutability**
Rate cards follow a state progression to prevent retroactive changes:

| State | Description | Editable Fields | Trigger |
|-------|-------------|-----------------|---------|
| **draft** | Initial state, fully editable | All fields | Manual entry |
| **locked** | Used by validated timesheets | Only notes, non-pricing fields | Timesheet validation (future module) |
| **invoiced_locked** | Used by invoices, fully immutable | Only notes | Invoice creation (future module) |

**Immutability Rules:**
- `locked`: Cannot change pricing-critical fields (company, client, product, employee, currency, rate, dates, project)
- `invoiced_locked`: Cannot change anything except notes
- Cannot deactivate locked/invoiced entries (use `date_end` to prevent future use instead)

### 5. **Historical Auditability**
- Tracks who and when entries were locked/invoiced
- Prevents retroactive changes that would affect historical timesheets/invoices
- Supports audit trails via chatter (mail.thread integration)

---

## Installation

### Prerequisites
- Odoo 17.0 Enterprise
- Dependencies: `base`, `hr`, `product`, `project`, `mail`

### Steps
1. Place the `tm_rate_card` folder in your `addons` path
2. Update the app list: `Settings > Apps > Update Apps List`
3. Search for "Rate Card Management"
4. Click **Install**

---

## Configuration

### 1. **Assign User Groups**
Navigate to: `Settings > Users & Companies > Users`

**Groups:**
- **Rate Card Viewer**: Read-only access to rate cards
- **Rate Card Manager**: Full CRUD access (subject to governance rules)

Recommended assignments:
- Finance team → Manager
- Sales team → Manager
- Project managers → Viewer
- Employees → Viewer (if needed)

### 2. **Create Rate Card Entries**
Navigate to: `Rate Cards > Configuration > Rate Card Entries`

**Required fields:**
- Company
- Client
- Service Product (e.g., "Dev Hour", "PM Hour")
- Employee
- Currency
- Rate (monetary value)
- Valid From (date_start)

**Optional fields:**
- Specific Project (leave blank for client-wide rate)
- Valid Until (date_end - leave blank for open-ended)
- Notes

**Tips:**
- Start with **client-wide** rates (project blank) for simplicity
- Add **project-specific** rates only when needed (they take priority)
- Use **date_end** to phase out old rates without deleting history
- Use **Active** toggle to soft-delete draft entries

---

## Usage

### Creating Rate Cards

**Scenario 1: Client-wide rate**
```
Client: ACME Corp
Project: (blank)
Service Product: Dev Hour
Employee: John Doe
Rate: $150/hour
Valid From: 2026-01-01
Valid Until: (blank - open-ended)
```
→ This rate applies to **all projects** for ACME Corp when John works on "Dev Hour" tasks.

**Scenario 2: Project-specific override**
```
Client: ACME Corp
Project: Project Phoenix
Service Product: Dev Hour
Employee: John Doe
Rate: $175/hour
Valid From: 2026-02-01
Valid Until: 2026-06-30
```
→ This rate applies **only to Project Phoenix** during Feb-June 2026. Outside this period or project, the client-wide rate applies.

### Rate Resolution Logic

When the resolution service is called, it:

1. **Filters** by company, client, service product, employee, currency
2. **Filters** by date: `date_start <= date AND (date_end >= date OR date_end IS NULL)`
3. **Tries** project-specific match first (if project provided)
4. **Falls back** to client-wide match (project_id = False)
5. **Returns** exactly one entry or raises `ValidationError`

**Resolution method:**
```python
entry = self.env['tm.rate.card.entry'].resolve_rate(
    company=res.company,
    client=res.partner,
    service_product=product.product,
    employee=hr.employee,
    currency=res.currency,
    date=date,
    project=project.project or None,
)
```

**Debugging helper:**
```python
result = self.env['tm.rate.card.entry'].explain_resolution(...)
# Returns dict with success, entry_id, rate, scope, error, etc.
```

---

## Integration Points (Future Modules)

### Timesheet Validation Module
When timesheets are validated, the validation module should:

1. Resolve rate card for each timesheet line
2. Store rate card entry reference on timesheet line
3. Call `rate_entry.action_lock()` to transition to `locked` state

**Example:**
```python
# In timesheet validation workflow
for line in timesheet.line_ids:
    rate_entry = self.env['tm.rate.card.entry'].resolve_rate(
        company=line.company_id,
        client=line.project_id.partner_id,
        service_product=line.product_id,
        employee=line.employee_id,
        currency=line.company_id.currency_id,
        date=line.date,
        project=line.project_id,
    )
    line.rate_card_entry_id = rate_entry.id  # Store reference
    rate_entry.action_lock()  # Lock rate card
```

### Invoicing Module
When invoices are created from timesheets, the invoicing module should:

1. Read rate card reference from timesheet lines
2. Call `rate_entry.action_invoiced_lock()` to transition to `invoiced_locked` state

**Example:**
```python
# In invoice creation workflow
rate_entries = timesheet_lines.mapped('rate_card_entry_id')
rate_entries.action_invoiced_lock()  # Permanently lock rate cards
```

---

## State Transition Methods

The module provides public API methods for state transitions:

### `action_lock()`
Transitions: `draft → locked`

**Use case:** Called by timesheet validation module when timesheets using this rate are validated.

**Effect:**
- Sets `state = 'locked'`
- Records `locked_at` and `locked_by`
- Prevents editing of pricing-critical fields

### `action_invoiced_lock()`
Transitions: `draft/locked → invoiced_locked`

**Use case:** Called by invoicing module when invoices using this rate are created.

**Effect:**
- Sets `state = 'invoiced_locked'`
- Records `invoiced_locked_at` and `invoiced_locked_by`
- Prevents editing of all fields except notes

### `action_unlock()`
Transitions: `locked → draft`

**Use case:** Admin override for corrections before invoicing.

**Effect:**
- Sets `state = 'draft'`
- Clears `locked_at` and `locked_by`
- **Cannot** unlock `invoiced_locked` entries

---

## Data Model Reference

### Model: `tm.rate.card.entry`

**Key Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `company_id` | Many2one(res.company) | Company (multi-company support) |
| `client_id` | Many2one(res.partner) | Customer |
| `project_id` | Many2one(project.project) | Optional project (for project-specific rates) |
| `service_product_id` | Many2one(product.product) | Service product (e.g., "Dev Hour") |
| `employee_id` | Many2one(hr.employee) | Employee |
| `currency_id` | Many2one(res.currency) | Currency |
| `rate` | Monetary | Billable rate |
| `date_start` | Date | Effective start date (inclusive) |
| `date_end` | Date | Effective end date (inclusive, blank = open) |
| `state` | Selection | draft / locked / invoiced_locked |
| `active` | Boolean | Active flag (for soft deletion) |
| `notes` | Text | Internal notes |

**Constraints:**
- No overlapping date ranges for same unique combination
- `date_end >= date_start` if both set
- Multi-company: users only see entries in allowed companies

---

## Troubleshooting

### Error: "Overlapping rate card entry detected"
**Cause:** Trying to create/edit an entry with date range that overlaps an existing active entry for the same combination.

**Solution:**
1. Check existing entries: filter by client, project, service product, employee
2. Adjust date ranges to be non-overlapping
3. Use `date_end` to close old entries before creating new ones
4. Or deactivate the old draft entry if it's not yet used

### Error: "No matching rate card entry found"
**Cause:** Resolution service couldn't find a rate for the given combination and date.

**Solution:**
1. Verify rate card exists for that client/employee/product/date
2. Check if rate is marked as `active = True`
3. Check if date falls within `date_start` to `date_end` range
4. If project-specific rate expected, verify it exists; otherwise ensure client-wide rate exists

### Error: "Cannot modify ... - entry is locked"
**Cause:** Trying to edit pricing fields on a locked entry.

**Solution:**
- If entry not yet invoiced: Use `action_unlock()` button (Manager only) to unlock, then edit
- If entry is invoiced: Cannot edit. Create a new entry with future `date_start` instead

### Deactivation blocked
**Cause:** Trying to deactivate (archive) a locked or invoiced entry.

**Solution:**
- Set `date_end` to a past date to prevent future use while preserving history
- Deactivation only allowed for draft entries

---

## Security

### Multi-Company
- Record rule enforces: `[('company_id', 'in', company_ids)]`
- Users only see rate cards in companies they have access to
- `_check_company_auto = True` ensures automatic company consistency checks

### Access Rights

| Group | Read | Write | Create | Delete |
|-------|------|-------|--------|--------|
| Rate Card Viewer | ✅ | ❌ | ❌ | ❌ |
| Rate Card Manager | ✅ | ✅ | ✅ | ✅ |

**Note:** Even Managers are subject to governance rules (cannot edit locked/invoiced fields via write() override).

---

## Technical Notes

### Odoo 17 Patterns Used
- **Date overlap constraint**: Pattern from `hr_contract` (expression.AND with open-ended handling)
- **State management**: Pattern from `hr_payslip` (state field with write() override)
- **Deterministic matching**: Pattern from `product_pricelist` (domain construction, priority rules)
- **Multi-company**: Standard `company_ids` record rule + `_check_company_auto`
- **Monetary fields**: Pattern from `hr_contract` (Monetary field with currency_id)

### Performance Considerations
- Date fields (`date_start`, `date_end`) are indexed for fast queries
- Constraint checks only run on active entries
- Resolution service uses `limit=2` to detect data integrity issues efficiently
- Consider adding `@ormcache` to `resolve_rate()` if called very frequently (not implemented by default)

### Dependencies for Future Modules
To integrate with this module, future modules need:

**Timesheet validation module:**
- Add field: `account.analytic.line.rate_card_entry_id` (Many2one to tm.rate.card.entry)
- Call `resolve_rate()` during validation
- Call `action_lock()` after validation

**Invoicing module:**
- Read `rate_card_entry_id` from timesheet lines
- Call `action_invoiced_lock()` after invoice confirmation

---

## Support

For issues or questions:
- Review the **GUIDANCE.md** file in the module directory
- Check Odoo logs for detailed error messages
- Verify your rate card data using filters: Configuration > Rate Cards > Rate Card Entries

---

## License

LGPL-3

---

## Changelog

### Version 1.0.0 (2026-01-27)
- Initial release
- Core rate card model with multi-dimensional matching
- Deterministic resolution service
- Governance states (draft, locked, invoiced_locked)
- Immutability rules enforcement
- Multi-company support
- Basic UI (tree, form, search views)
- Integration points for future modules

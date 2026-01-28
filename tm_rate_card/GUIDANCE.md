# tm_rate_card Module - Developer Guidance

## Module Purpose

The `tm_rate_card` module serves as the **single source of truth** for Time & Materials (T&M) pricing in the Odoo ERP system. It provides a deterministic rate resolution engine with governance controls to ensure pricing integrity from timesheet entry through invoicing.

**Scope:** This module handles ONLY rate card master data and resolution logic. It does NOT handle timesheet validation, invoicing, or external system integration.

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
| `locked` | `notes`, `active` (with restrictions) | All pricing-critical fields* |
| `invoiced_locked` | `notes` only | Everything else |

*Pricing-critical fields: `company_id`, `client_id`, `service_product_id`, `employee_id`, `currency_id`, `rate`, `date_start`, `date_end`, `project_id`

**Deactivation Rules:**
- `draft` → can deactivate
- `locked` or `invoiced_locked` → **cannot deactivate** (use `date_end` instead to preserve history)

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

### For Future Timesheet Validation Module

**Requirements:**
1. Add field to timesheet line: `rate_card_entry_id` (Many2one to `tm.rate.card.entry`)
2. On validation, call resolution service:
   ```python
   rate_entry = self.env['tm.rate.card.entry'].resolve_rate(
       company=line.company_id,
       client=line.project_id.partner_id,
       service_product=line.product_id,
       employee=line.employee_id,
       currency=line.company_id.currency_id,
       date=line.date,
       project=line.project_id,
   )
   line.rate_card_entry_id = rate_entry.id
   ```
3. After validation, lock rate cards:
   ```python
   rate_entries = validated_lines.mapped('rate_card_entry_id')
   rate_entries.action_lock()
   ```

**Why store reference?**
- Preserves exact rate used (even if rate card changes later)
- Enables traceability for invoicing
- Allows bulk locking of rate cards

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

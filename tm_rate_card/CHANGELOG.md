# Changelog - Rate Card Management Module

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

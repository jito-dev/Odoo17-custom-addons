# Rate Card Module v1.6.0 - Timesheet Tracking Feature

**Date**: 2026-01-28
**Version**: 1.6.0 (major feature release)

## New Feature: Timesheet Tracking & Billing Analytics

View validated timesheet entries directly from Rate Card Entry records, with automatic calculation of hours, rates, and billable amounts.

---

## What's New

### ✅ Timesheet Integration
- **View all timesheets** that used a specific rate card entry
- **Track usage** of rate cards across projects
- **Monitor billing** - see hours tracked and amounts billed

### ✅ Automatic Calculations
- **Total Hours** - Sum of all timesheet hours using this rate
- **Total Billable Amount** - Automatic calculation (hours × rate)
- **Timesheet Count** - Number of timesheet entries

### ✅ Detailed Views
- **Timesheet list** with employee, project, task, description
- **Statistics summary** showing totals at a glance
- **Tree view columns** showing usage metrics

---

## Features Added

### 1. **Timesheet Tab in Rate Card Entry**

Open any Rate Card Entry and you'll see a new **"Timesheets" tab** with:

#### Statistics Section
```
┌─────────────────────────────────────────┐
│ Timesheet Statistics:                   │
│ • Timesheet Count: 45                   │
│ • Total Hours: 180.5 hours              │
│ • Total Billable Amount: $27,075.00     │
│                                         │
│ Rate Information:                       │
│ • Rate: $150.00 / hour                  │
│ • Effective Period: 2024-01-01 → ∞     │
└─────────────────────────────────────────┘
```

#### Timesheet Entries List
```
| Date       | Employee  | Project   | Task      | Hours | Rate    | Billable  |
|------------|-----------|-----------|-----------|-------|---------|-----------|
| 2024-01-15 | John Doe  | Project X | Task A    | 8.0   | $150.00 | $1,200.00 |
| 2024-01-16 | John Doe  | Project X | Task B    | 6.5   | $150.00 | $975.00   |
| ...        | ...       | ...       | ...       | ...   | ...     | ...       |
```

### 2. **Enhanced Tree View**

Rate Card Entry list now shows:
- **Timesheets** - Number of timesheet entries
- **Hours Tracked** - Total hours across all timesheets
- **Billed Amount** - Total billable amount

### 3. **New Fields on Timesheets**

Each timesheet entry (`account.analytic.line`) now has:
- **Rate Card Entry** - Link to the rate card used
- **Billing Rate** - Rate applied to this timesheet
- **Billable Amount** - Calculated amount (hours × rate)

---

## Technical Details

### New Model: Account Analytic Line Extension

**File**: `models/account_analytic_line.py`

```python
class AccountAnalyticLine(models.Model):
    _inherit = 'account.analytic.line'

    # Link to rate card
    tm_rate_card_entry_id = fields.Many2one(
        'tm.rate.card.entry',
        string='Rate Card Entry',
    )

    # Billing rate
    tm_billing_rate = fields.Monetary(
        string='Billing Rate',
    )

    # Billable amount (computed)
    tm_billable_amount = fields.Monetary(
        string='Billable Amount',
        compute='_compute_tm_billable_amount',
        store=True,
    )
```

### New Fields on Rate Card Entry

**File**: `models/tm_rate_card_entry.py`

```python
# Timesheet relationship
timesheet_ids = fields.One2many(
    'account.analytic.line',
    'tm_rate_card_entry_id',
    string='Timesheets',
)

# Statistics (computed)
timesheet_count = fields.Integer(compute='_compute_timesheet_stats')
timesheet_hours = fields.Float(compute='_compute_timesheet_stats')
timesheet_amount = fields.Monetary(compute='_compute_timesheet_stats')
```

### Compute Method

```python
@api.depends('timesheet_ids', 'timesheet_ids.unit_amount',
             'timesheet_ids.tm_billable_amount')
def _compute_timesheet_stats(self):
    """Compute statistics from related timesheets"""
    for entry in self:
        timesheets = entry.timesheet_ids
        entry.timesheet_count = len(timesheets)
        entry.timesheet_hours = sum(timesheets.mapped('unit_amount'))
        entry.timesheet_amount = sum(timesheets.mapped('tm_billable_amount'))
```

---

## How It Works

### Workflow

1. **Rate Card Created** → RCE00001 with rate $150/hour
2. **Timesheet Entered** → Employee logs 8 hours on Project X
3. **Rate Applied** → System links timesheet to RCE00001
4. **Billing Calculated** → 8 hours × $150 = $1,200
5. **Stats Updated** → Rate card shows 1 timesheet, 8 hours, $1,200

### Data Flow

```
Rate Card Entry (RCE00001)
    ↓
Applied to Timesheet Entry
    ↓
Billing Rate: $150/hour
Hours: 8.0
    ↓
Billable Amount: $1,200
    ↓
Aggregated to Rate Card Stats:
- Total Hours: 8.0
- Total Amount: $1,200
```

---

## Usage Examples

### View Timesheets for a Rate Card

1. Go to **Rate Cards → Rate Card Entries**
2. Open a Rate Card Entry (e.g., RCE00001)
3. Click **"Timesheets" tab**
4. See:
   - Statistics summary at top
   - List of all timesheets below

### Check Rate Card Usage

In the **Rate Card Entry list view**:
- Look at "Timesheets" column → Number of timesheet entries
- Look at "Hours Tracked" → Total hours logged
- Look at "Billed Amount" → Total revenue from this rate

### Filter High-Usage Rate Cards

1. Go to Rate Card Entry list
2. Group by: **Timesheets** or **Hours Tracked**
3. Sort by **Billed Amount** (descending)
4. See which rate cards are generating most revenue

---

## Benefits

### For Finance Team
- ✅ **Revenue tracking** - See billable amounts per rate card
- ✅ **Usage monitoring** - Identify frequently used rates
- ✅ **Audit trail** - Full history of timesheet billing

### For Project Managers
- ✅ **Resource tracking** - See how much time logged at each rate
- ✅ **Cost visibility** - Monitor project costs by rate card
- ✅ **Utilization** - Track employee time by billing rate

### For Billing Team
- ✅ **Invoice preparation** - Quick view of billable amounts
- ✅ **Rate validation** - Verify correct rates were applied
- ✅ **Client reporting** - Breakdown by rate card

---

## Upgrade Instructions

### Prerequisites

- ✅ **hr_timesheet module** must be installed
- ✅ **Timesheet data** should exist to see results
- ✅ **Rate cards** should be created first

### Step 1: Check Dependencies

Ensure `hr_timesheet` is installed:
1. Go to **Apps**
2. Search: "Timesheets"
3. If not installed, install it first

### Step 2: Restart Odoo

```bash
sudo systemctl restart odoo
```

### Step 3: Upgrade Module

1. Go to **Apps** menu
2. Remove "Apps" filter
3. Search: **Rate Card**
4. Version should show **1.6.0**
5. Click **Upgrade**

### Step 4: Verify Installation

1. Open any Rate Card Entry
2. You should see **"Timesheets" tab**
3. If timesheets are already linked, stats will show
4. If no timesheets linked yet, stats will show zeros

---

## Linking Timesheets to Rate Cards

**Important**: This module adds the **fields and views**, but does NOT automatically link existing timesheets to rate cards.

### To Link Timesheets:

You need separate logic (in another module or script) to:
1. When a timesheet is created/validated
2. Find the matching rate card entry using `resolve_rate()` method
3. Set `tm_rate_card_entry_id` on the timesheet
4. Set `tm_billing_rate` from the rate card
5. Billable amount will auto-calculate

### Example Integration Code:

```python
# In your timesheet validation module
def validate_timesheet(timesheet):
    # Find matching rate card
    rate_card = env['tm.rate.card.entry'].resolve_rate(
        company=timesheet.company_id,
        client=timesheet.project_id.partner_id,
        service_product=timesheet.product_id,  # service product
        employee=timesheet.employee_id,
        currency=timesheet.currency_id,
        date=timesheet.date,
        project=timesheet.project_id,
    )

    # Link timesheet to rate card
    timesheet.write({
        'tm_rate_card_entry_id': rate_card.id,
        'tm_billing_rate': rate_card.rate,
    })
    # tm_billable_amount will compute automatically
```

---

## Data Migration

### For Existing Timesheets

If you have existing timesheets and want to link them to rate cards:

```python
# Python script to link historical timesheets
timesheets = env['account.analytic.line'].search([
    ('project_id', '!=', False),
    ('employee_id', '!=', False),
    ('tm_rate_card_entry_id', '=', False),  # Not yet linked
])

for timesheet in timesheets:
    try:
        # Find matching rate card
        rate_card = env['tm.rate.card.entry'].resolve_rate(
            company=timesheet.company_id,
            client=timesheet.project_id.partner_id,
            service_product=timesheet.product_id,
            employee=timesheet.employee_id,
            currency=timesheet.currency_id,
            date=timesheet.date,
            project=timesheet.project_id,
        )

        # Link it
        timesheet.write({
            'tm_rate_card_entry_id': rate_card.id,
            'tm_billing_rate': rate_card.rate,
        })

        print(f"Linked timesheet {timesheet.id} to {rate_card.reference}")

    except ValidationError as e:
        print(f"No rate card found for timesheet {timesheet.id}: {e}")
```

---

## Views & UI

### Files Added/Modified

1. **`models/account_analytic_line.py`** - NEW: Timesheet extensions
2. **`models/tm_rate_card_entry.py`** - UPDATED: Added timesheet fields
3. **`views/tm_rate_card_timesheet_views.xml`** - NEW: Timesheet tree view
4. **`views/tm_rate_card_entry_views.xml`** - UPDATED: Added Timesheets tab
5. **`security/ir.model.access.csv`** - UPDATED: Added analytic line access

### Form View Changes

**Before (v1.5.0):**
```
Notebook:
- Notes
```

**After (v1.6.0):**
```
Notebook:
- Timesheets ← NEW!
  - Statistics summary
  - Timesheet entries list
- Notes
```

### Tree View Changes

**New columns** (optional, can be shown/hidden):
- Timesheets
- Hours Tracked
- Billed Amount

---

## Security

### Access Rights

- **Rate Card Viewer**: Can view timesheets (read-only)
- **Rate Card Manager**: Can view timesheets (read-only)
- **Note**: Cannot create/edit timesheets from rate card view

Timesheets are managed through the Timesheets module. Rate card only provides a **read-only view**.

---

## Testing Checklist

After upgrade, test:

- [ ] Rate Card Entry has "Timesheets" tab
- [ ] Statistics show correct totals (if timesheets linked)
- [ ] Timesheet list displays correctly
- [ ] Tree view shows new columns (optional)
- [ ] Cannot create/edit timesheets from rate card view (read-only)
- [ ] Stats update when timesheets are linked
- [ ] Billable amount calculates correctly (hours × rate)

---

## Troubleshooting

### Issue: Timesheets tab is empty

**Cause**: No timesheets linked to this rate card yet

**Fix**: Timesheets need to be linked via code when validated (see "Linking Timesheets to Rate Cards" section above)

### Issue: Stats show zero

**Cause**: Same as above - no linked timesheets

**Fix**: Link timesheets using the resolve_rate() method

### Issue: Cannot see Timesheets tab

**Cause**: hr_timesheet module not installed

**Fix**:
1. Install hr_timesheet module
2. Restart Odoo
3. Upgrade rate card module

### Issue: Permission error viewing timesheets

**Cause**: User doesn't have access to rate card groups

**Fix**: Assign user to "Rate Card Viewer" or "Rate Card Manager" group

---

## Future Enhancements

Potential future features:
- Automatic timesheet linking on validation
- Timesheet approval workflow
- Invoice generation from rate cards
- Export timesheet data
- Timesheet vs. budgeted hours comparison
- Rate card usage reports

---

## Files Changed

1. `__manifest__.py` - Version bump, added hr_timesheet dependency
2. `models/__init__.py` - Added account_analytic_line import
3. `models/account_analytic_line.py` - NEW: Timesheet extensions
4. `models/tm_rate_card_entry.py` - Added timesheet tracking fields
5. `views/tm_rate_card_entry_views.xml` - Added Timesheets tab
6. `views/tm_rate_card_timesheet_views.xml` - NEW: Timesheet views
7. `security/ir.model.access.csv` - Added analytic line access

---

## Summary

**What's new**: View timesheets and billing analytics per rate card
**Why**: Track usage, monitor billing, audit trail
**Impact**: Adds timesheet visibility; requires linking logic in separate module
**Version**: 1.6.0 (major feature release)

This feature provides visibility into how rate cards are being used in practice, enabling better financial tracking and project management.

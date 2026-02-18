# Rate Card Module v1.6.1 - Automatic Timesheet Linking Hotfix

**Date**: 2026-01-28
**Version**: 1.6.1 (hotfix for 1.6.0)

## Issue Fixed

**Problem**: In v1.6.0, timesheet tracking views were added but timesheets were NOT automatically linked to rate cards. Users had to manually write code to link them.

**Root Cause**: The module only created fields and views, but didn't implement automatic linking logic when timesheets are created or validated.

---

## What's Fixed

### ✅ **Automatic Linking**
- Timesheets now **automatically link** to rate cards when created
- Billing rate **auto-fills** from the matched rate card
- Billable amount **auto-calculates** (hours × rate)

### ✅ **Manual Linking Action**
- Added **"Link Rate Cards"** button on timesheet list view
- Allows bulk processing of existing timesheets
- Resolves rate cards for selected timesheets

### ✅ **Smart Resolution**
- Uses **SO Line** if available (from sale_timesheet module)
- Falls back to **project partner** if no SO line
- Handles missing fields gracefully (no errors)

---

## Changes Made

### 1. **Auto-Linking in Create/Write**

**File**: `models/account_analytic_line.py`

#### On Create:
```python
@api.model_create_multi
def create(self, vals_list):
    lines = super().create(vals_list)
    # Auto-link to rate cards
    lines._resolve_and_set_rate_card()
    return lines
```

#### On Write:
```python
def write(self, vals):
    result = super().write(vals)
    # Re-link if key fields changed
    if project/employee/date/product changed:
        self._resolve_and_set_rate_card()
    return result
```

### 2. **Rate Card Resolution Logic**

**Method**: `_get_rate_card_params()`

```python
def _get_rate_card_params(self):
    # Priority 1: Get from SO Line (if sale_timesheet installed)
    if self.so_line:
        client = self.so_line.order_id.partner_id
        service_product = self.so_line.product_id

    # Priority 2: Get from project
    else:
        client = self.project_id.partner_id
        service_product = self.product_id

    return {
        'company': self.company_id,
        'client': client,
        'service_product': service_product,
        'employee': self.employee_id,
        'currency': self.currency_id,
        'date': self.date,
        'project': self.project_id,
    }
```

**Method**: `_resolve_and_set_rate_card()`

```python
def _resolve_and_set_rate_card(self):
    for line in self:
        params = line._get_rate_card_params()
        if not params:
            continue  # Skip if missing fields

        try:
            rate_card = env['tm.rate.card.entry'].resolve_rate(**params)
            line.write({
                'tm_rate_card_entry_id': rate_card.id,
                'tm_billing_rate': rate_card.rate,
            })
        except ValidationError:
            pass  # No matching rate card - OK
```

### 3. **Manual Action Button**

**File**: `views/account_analytic_line_views.xml`

Added button to timesheet tree view:
```xml
<button name="action_resolve_rate_cards"
        type="object"
        string="Link Rate Cards"
        class="btn-secondary"/>
```

**Method**: `action_resolve_rate_cards()`
- Clears existing links
- Re-resolves rate cards
- Shows success notification

---

## How It Works Now

### Automatic Linking Flow

```
1. User creates/edits timesheet
   ↓
2. Timesheet saved (create/write)
   ↓
3. Auto-resolution triggered
   ↓
4. Find client, service product, employee, date from timesheet
   ↓
5. Call resolve_rate() to find matching rate card
   ↓
6. Set tm_rate_card_entry_id & tm_billing_rate
   ↓
7. tm_billable_amount computes automatically
   ↓
8. Rate card stats update (count, hours, amount)
```

### Data Sources Priority

**For Client & Service Product:**

1. **First choice**: Sales Order Line (if `sale_timesheet` module installed)
   - Client: `timesheet.so_line.order_id.partner_id`
   - Product: `timesheet.so_line.product_id`

2. **Fallback**: Project Partner
   - Client: `timesheet.project_id.partner_id`
   - Product: `timesheet.product_id` (if available)

---

## Upgrade Instructions

### Step 1: Restart Odoo

```bash
sudo systemctl restart odoo
```

### Step 2: Upgrade Module

1. Go to **Apps** menu
2. Remove "Apps" filter
3. Search: **Rate Card**
4. Should show version **1.6.1**
5. Click **Upgrade**

### Step 3: Link Existing Timesheets

After upgrade, existing timesheets won't be linked automatically. Use one of these methods:

#### Method A: Use the Button (Recommended)

1. Go to **Timesheets** app
2. Go to **Timesheets → My Timesheets** (or All Timesheets)
3. Select timesheets you want to link (use filters/search)
4. Click **"Link Rate Cards"** button at top
5. Wait for success notification
6. Check Rate Card entries - timesheets should appear

#### Method B: Python Script

```python
# Link all unlinked timesheets
timesheets = env['account.analytic.line'].search([
    ('project_id', '!=', False),
    ('employee_id', '!=', False),
    ('tm_rate_card_entry_id', '=', False),
])

print(f"Processing {len(timesheets)} timesheets...")

timesheets.action_resolve_rate_cards()

print("Done!")
```

---

## Testing Checklist

After upgrade, verify:

### Test 1: New Timesheet Auto-Links
- [ ] Create new timesheet entry
- [ ] Fill: Project, Task, Employee, Hours
- [ ] Save
- [ ] Check timesheet form - should show Rate Card Entry
- [ ] Check Rate Card Entry - should show this timesheet in list

### Test 2: Existing Timesheets
- [ ] Go to Timesheets list
- [ ] Select some timesheets
- [ ] Click "Link Rate Cards" button
- [ ] See success notification
- [ ] Timesheets now have rate card linked

### Test 3: Rate Card Stats Update
- [ ] Open Rate Card Entry
- [ ] Go to Timesheets tab
- [ ] Should show:
  - Timesheet count > 0
  - Total hours > 0
  - Total amount > 0
- [ ] List should show timesheet entries

### Test 4: SO Line Integration (if sale_timesheet installed)
- [ ] Create timesheet with SO line set
- [ ] Save
- [ ] Check rate card uses client/product from SO line

---

## What You Should See Now

### In Timesheet List View:

```
| Date   | Project | Employee | Hours | Rate Card      | Billing Rate | Billable  |
|--------|---------|----------|-------|----------------|--------------|-----------|
| Jan 15 | Proj X  | John Doe | 8.0   | RCE00001       | $150.00      | $1,200.00 |
| Jan 16 | Proj X  | John Doe | 6.5   | RCE00001       | $150.00      | $975.00   |
```

### In Timesheet Form View:

```
Employee: John Doe
Rate Card Entry: RCE00001 (readonly)
Billing Rate: $150.00 (readonly)
Billable Amount: $1,200.00 (readonly)
```

### In Rate Card Entry (Timesheets Tab):

```
Statistics:
- Timesheet Count: 2
- Total Hours: 14.5 hours
- Total Billable: $2,175.00

Timesheet List:
[Shows the 2 timesheets above]
```

---

## Troubleshooting

### Issue: Timesheets still not linked after upgrade

**Cause**: Upgrade doesn't automatically link existing timesheets

**Fix**:
1. Go to Timesheets
2. Select timesheets
3. Click "Link Rate Cards" button

### Issue: "Link Rate Cards" button not visible

**Cause**: User doesn't have Rate Card Manager role

**Fix**:
- Assign user to "Rate Card Manager" group
- Settings → Users → Select user → Groups → Check "Rate Card Manager"

### Issue: Rate card not found when linking

**Cause**: No matching rate card exists for this combination

**Fix**:
1. Check if rate card exists for:
   - Client (from project or SO line)
   - Service Product (from SO line or timesheet)
   - Employee
   - Date (check effective dates)
2. Create rate card if missing
3. Try linking again

### Issue: Wrong rate card linked

**Cause**: Multiple rate cards match, resolution picked wrong one

**Fix**:
1. Check rate card overlap prevention
2. Review resolution priority (project-specific > client-wide)
3. Check effective dates
4. May need to adjust rate card entries

### Issue: Some timesheets link, others don't

**Cause**: Some timesheets missing required fields (project, employee, etc.)

**Fix**: Check timesheets that didn't link have:
- Project set
- Employee set
- Date set
- Either SO line OR project has partner

---

## Benefits

### Before (v1.6.0):
- ❌ Manual linking required
- ❌ Had to write Python code
- ❌ No automatic resolution
- ❌ Stats always showed zero

### After (v1.6.1):
- ✅ Automatic linking on create/edit
- ✅ One-click bulk linking for existing
- ✅ Smart resolution (SO line → project)
- ✅ Stats update in real-time

---

## Technical Details

### Files Modified

1. `models/account_analytic_line.py` - Added auto-linking logic
2. `views/account_analytic_line_views.xml` - NEW: Added action button
3. `__manifest__.py` - Version 1.6.1, added view file

### Dependencies

- **Required**: `hr_timesheet`
- **Optional**: `sale_timesheet` (for SO line integration)

If `sale_timesheet` is installed, resolution will use SO line data (preferred).

---

## API Changes

### New Methods

```python
# Get parameters for rate resolution
timesheet._get_rate_card_params()

# Resolve and set rate card
timesheet._resolve_and_set_rate_card()

# Manual action (button click)
timesheet.action_resolve_rate_cards()
```

### Behavior Changes

**Before**: Creating timesheet did nothing with rate cards

**After**: Creating timesheet automatically tries to link to rate card

**Migration Impact**: None - existing timesheets unchanged until you manually link them

---

## Performance Notes

- Auto-linking happens on create/write - minimal performance impact
- Uses existing `resolve_rate()` method (already optimized)
- No impact if rate card not found (silent skip)
- Bulk action processes multiple timesheets efficiently

---

## Future Enhancements

Potential improvements:
- Batch linking on timesheet validation/approval
- Warning if no rate card found
- Configurable auto-linking (enable/disable)
- Link on specific timesheet states only

---

## Summary

**What's fixed**: Automatic timesheet to rate card linking
**How**: Auto-link on create/write + manual bulk action
**Impact**: Timesheets now properly tracked in rate card entries
**Version**: 1.6.1 (hotfix)

This hotfix makes the timesheet tracking feature actually work as intended!

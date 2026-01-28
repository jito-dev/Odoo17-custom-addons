# Rate Card Module v1.7.0 - Validation Integration

**Date**: 2026-01-28
**Version**: 1.7.0 (feature release)

## What's New

✅ **Automatic rate card linking when you validate timesheets**
✅ **Seamless integration with timesheet validation workflow**
✅ **No extra steps needed - validate and you're done!**

---

## The Big Change

### Before (v1.6.x):
1. Validate timesheets ✅
2. Separately click "Link Rate Cards" ⚠️
3. Two steps, easy to forget

### After (v1.7.0):
1. Validate timesheets ✅
2. **Done!** Rate cards link automatically 🎉
3. One step, seamless

---

## How It Works Now

When you click **"Validate"** on timesheets:

1. **Timesheets are validated** (marked as approved, locked)
2. **Rate cards are automatically linked** (finds matching rate card)
3. **Billing rates are set** (from rate card)
4. **Billable amounts calculated** (hours × rate)
5. **Stats updated** (rate card shows new timesheets)

**You don't need to do anything else!**

---

## When to Use Each Button

### Use "Validate" Button (Your Main Workflow)
- ✅ End of week/period when approving timesheets
- ✅ When marking time as billable
- ✅ After reviewing employee timesheets
- **Does**: Validates + Links rate cards + Sets rates

### Use "Link Rate Cards" Button (Special Cases Only)
- ⚠️ After upgrading module (for old timesheets)
- ⚠️ Bulk-fixing historical data
- ⚠️ Re-linking after creating missing rate cards
- **Does**: Links rate cards only (doesn't validate)

---

## Your New Workflow

### Simple 3-Step Process:

1. **Employees log time** during the week
2. **Review timesheets** at end of period
3. **Click "Validate"** → Everything happens automatically!

That's it! Rate cards link automatically when you validate.

---

## Upgrade Instructions

### Step 1: Restart Odoo
```bash
sudo systemctl restart odoo
```

### Step 2: Upgrade Module
1. Apps → Search "Rate Card"
2. Version should show **1.7.0**
3. Click Upgrade

### Step 3: Link Existing Validated Timesheets

If you have old timesheets that were validated before this upgrade:
1. Go to Timesheets
2. Filter: Validated + No Rate Card
3. Select all
4. Click "Link Rate Cards" button
5. Done!

### Step 4: Test

Create and validate a new timesheet:
1. Create timesheet (Project, Employee, Hours)
2. Click "Validate"
3. Check timesheet → Should show Rate Card, Billing Rate, Billable Amount ✅
4. Check Rate Card Entry → Should show timesheet in list ✅

---

## Technical Details

### New Method

**File**: `models/account_analytic_line.py`

```python
def action_validate_timesheet(self):
    """
    Override validation to auto-link rate cards.
    Hooks into timesheet_grid module's validation workflow.
    """
    # Call parent validation
    result = super().action_validate_timesheet()

    # Auto-link rate cards
    self._resolve_and_set_rate_card()

    return result
```

### How It Integrates

- If **timesheet_grid** module is installed → hooks into validation
- Extends existing `action_validate_timesheet()` method
- Rate card linking happens automatically after validation
- Silent failure if no rate card found (doesn't block validation)

---

## Benefits

### For Users:
- ✅ **Simpler workflow** - one button does everything
- ✅ **Less mistakes** - can't forget to link rate cards
- ✅ **Faster** - no extra step needed
- ✅ **Seamless** - feels like one integrated system

### For Finance:
- ✅ **Accurate billing** - rates always linked when validated
- ✅ **No missing data** - validation ensures rate cards are set
- ✅ **Audit trail** - validated timesheets = billable timesheets

---

## Comparison

### Old Way (v1.6.x):
```
Create Timesheet
    ↓
Validate Timesheet
    ↓
Manually click "Link Rate Cards" ⚠️
    ↓
Ready to Bill
```

### New Way (v1.7.0):
```
Create Timesheet
    ↓
Validate Timesheet ✅
    ↓
Ready to Bill (rate cards linked automatically!)
```

---

## Files Changed

1. `models/account_analytic_line.py` - Added validation hook
2. `__manifest__.py` - Version bump to 1.7.0

---

## Compatibility

- **Works with**: hr_timesheet (required)
- **Works with**: timesheet_grid (optional, enhanced integration)
- **Works with**: sale_timesheet (optional, uses SO line data)

If you don't have timesheet_grid:
- Validation hook won't activate
- Use "Link Rate Cards" button instead
- Everything else works the same

---

## Summary

**What's new**: Rate cards auto-link when validating timesheets
**Why**: Simpler workflow, less steps, fewer mistakes
**Impact**: Validation becomes one-stop action for timesheet approval + billing
**Version**: 1.7.0 (feature release)

Just click "Validate" and you're done! 🎉

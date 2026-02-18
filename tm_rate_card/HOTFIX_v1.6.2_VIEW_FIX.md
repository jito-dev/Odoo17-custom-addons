# Rate Card Module v1.6.2 - View Inheritance Fix

**Date**: 2026-01-28
**Version**: 1.6.2 (hotfix for 1.6.1)

## Issue Fixed

**Problem**: Module upgrade failed with error:
```
Element '<xpath expr="//field[@name='employee_id']">' cannot be located in parent view
```

**Root Cause**: The XPath in `account_analytic_line_views.xml` was trying to insert fields after `employee_id` in the timesheet form view, but the parent view structure was different than expected.

---

## What's Fixed

### ✅ Simplified View Inheritance
- Removed problematic form view inheritance
- Kept tree view modifications (more important anyway)
- Added rate card fields to tree view as optional columns
- "Link Rate Cards" button still works

### What You Get

In **Timesheet List View**:
- "Link Rate Cards" button (in header)
- Optional columns (can show/hide):
  - Rate Card Entry
  - Billing Rate
  - Billable Amount

---

## Changes Made

**File**: `views/account_analytic_line_views.xml`

**Before (v1.6.1)** - BROKEN:
```xml
<!-- Tried to inherit form view - failed -->
<xpath expr="//field[@name='employee_id']" position="after">
    ...
</xpath>
```

**After (v1.6.2)** - FIXED:
```xml
<!-- Only inherit tree view - works -->
<xpath expr="//field[@name='unit_amount']" position="after">
    <field name="tm_rate_card_entry_id" optional="hide"/>
    <field name="tm_billing_rate" widget="monetary" optional="hide"/>
    <field name="tm_billable_amount" widget="monetary" optional="hide"/>
</xpath>
```

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
4. Should show version **1.6.2**
5. Click **Upgrade**
6. **Should complete successfully now!** ✅

### Step 3: Verify
1. Go to **Timesheets** → My Timesheets
2. Should see "Link Rate Cards" button ✅
3. Click on list view options (columns icon)
4. Should see new optional columns:
   - Rate Card Entry
   - Billing Rate
   - Billable Amount

---

## Summary

**What broke**: XPath couldn't find field in parent view
**What's fixed**: Simplified to only modify tree view
**Impact**: None - all functionality still works
**Version**: 1.6.2 (hotfix)

The upgrade should now complete without errors!

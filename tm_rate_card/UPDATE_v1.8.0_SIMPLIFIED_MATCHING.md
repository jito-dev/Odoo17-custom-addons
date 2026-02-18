# Rate Card Module v1.8.0 - Simplified Timesheet Matching

**Date**: 2026-01-28
**Version**: 1.8.0 (major feature change)

## MAJOR CHANGE: Service Product No Longer Required!

✅ **Before (v1.7.x)**: Matching required service product (couldn't link without SO line)
✅ **After (v1.8.0)**: Matching simplified - only needs project, employee, date, active

---

## What Changed

### Old Matching (v1.7.x) - TOO STRICT
Timesheets had to match ALL of these:
- ❌ Company
- ❌ Client
- ❌ **Service Product** ← Problem: Timesheets don't have this!
- ❌ Employee
- ❌ Currency
- ❌ Date (within valid range)
- ❌ Project (optional)

**Result**: Most timesheets couldn't link because service product was missing.

### New Matching (v1.8.0) - SIMPLIFIED
Timesheets now match based on:
- ✅ Company
- ✅ Client (from project)
- ✅ Employee
- ✅ Date (within valid range)
- ✅ Project (optional - project-specific or client-wide)
- ℹ️ Service Product - NOT required for matching!

**Result**: Timesheets link easily! Service product is stored in rate card but not required to match.

---

## How It Works Now

### Matching Logic:

1. **Get timesheet data**:
   - Project: "Cheeeeezy Project"
   - Employee: "Administrator"
   - Date: 2026-01-28

2. **Extract client** from project:
   - Client: "Test Company" (from project partner)

3. **Search for rate card**:
   - Company = My Company
   - Client = Test Company
   - Employee = Administrator
   - Date within Valid From/Until range
   - Active = True
   - Project = "Cheeeeezy Project" (if project-specific rate exists)
     OR Project = blank (for client-wide rate)

4. **If found**: Link timesheet to rate card ✅

**Service product in the rate card entry is there for your reference/invoicing, but NOT used for matching timesheets!**

---

## What You Need to Create Rate Cards Now

### Minimal Requirements:

1. **Sales Order** → Pick any order for the client
2. **Client** → Auto-fills from SO
3. **Sales Order Line** → Pick any line (product doesn't matter for matching!)
4. **Service Product** → Auto-fills from SO line (stored for reference)
5. **Employee** → The employee to bill at this rate
6. **Rate** → Billing rate (e.g., $150.00)
7. **Valid From / Until** → Date range (or leave blank)
8. **Project** → Optional (leave blank for client-wide rate)

**That's it!** The service product is just metadata now.

---

## Matching Priority

When looking for rate cards for a timesheet:

### Priority 1: Project-Specific Rate
If rate card has `project_id` set → matches timesheets for that specific project

### Priority 2: Client-Wide Rate
If rate card has `project_id` blank → matches ALL timesheets for that client

### Example:

**You have 2 rate cards:**
- RCE001: Client=Acme, Employee=John, Project="Website", Rate=$150
- RCE002: Client=Acme, Employee=John, Project=blank, Rate=$120

**Timesheet matching:**
- Timesheet on "Website" project → Uses RCE001 ($150) ✅
- Timesheet on "Mobile App" project → Uses RCE002 ($120) ✅
- Project-specific always wins over client-wide

---

## Your Case - Should Work Now!

Based on your diagnostic:
```
Project: Cheeeeezy Project
Employee: Administrator
Client: Test Company
Date: 2026-01-28
```

**To fix**, create a rate card:
1. Rate Cards → Create
2. **Sales Order**: Any SO for "Test Company"
3. **Client**: Test Company (auto-fills)
4. **SO Line**: Any line (pick any product)
5. **Service Product**: (auto-fills - doesn't matter for matching)
6. **Employee**: Administrator
7. **Rate**: $150.00 (or your rate)
8. **Valid From**: 2026-01-28 (or blank)
9. **Valid Until**: (leave blank)
10. **Project**: "Cheeeeezy Project" (or blank for client-wide)
11. **Save**

Then:
1. Go to Timesheets
2. Select your timesheet
3. Click "Link Rate Cards"
4. Check Rate Card Entry → Should show your timesheet! ✅

---

## Benefits of Simplified Matching

### ✅ Easier Setup
- Don't need SO lines on every timesheet
- Works with basic timesheet data
- Service product is optional metadata

### ✅ More Flexible
- One rate card can match many different service types
- Client-wide rates work easily
- Project-specific rates still supported

### ✅ Less Friction
- Timesheets link immediately when validated
- No "missing service product" errors
- Works with standard Odoo timesheet workflow

---

## Migration Notes

### For Existing Rate Cards
**No changes needed!** Your existing rate cards will work fine. The service product is still there, just not used for timesheet matching.

### For Existing Timesheets
After upgrade:
1. Restart Odoo
2. Upgrade module to v1.8.0
3. Go to Timesheets
4. Select all timesheets
5. Click "Link Rate Cards"
6. They should link now! ✅

---

## Technical Details

### New Method: `resolve_rate_for_timesheet()`

**File**: `models/tm_rate_card_entry.py`

```python
@api.model
def resolve_rate_for_timesheet(self, company, client, employee, date, project=None):
    """
    Simplified rate resolution for timesheets.
    Matches based on: company, client, employee, date, project
    Service product NOT required!
    """
    base_domain = [
        ('active', '=', True),
        ('company_id', '=', company.id),
        ('client_id', '=', client.id),
        ('employee_id', '=', employee.id),
        # Date range check
        '|', ('date_start', '<=', date), ('date_start', '=', False),
        '|', ('date_end', '>=', date), ('date_end', '=', False),
    ]
    # Try project-specific, then client-wide
    ...
```

### Old Method Still Available

The original `resolve_rate()` method still exists for other uses (invoicing, etc.) that need service product matching.

---

## Upgrade Instructions

### Step 1: Restart Odoo
```bash
sudo systemctl restart odoo
```

### Step 2: Upgrade Module
1. Apps → Search "Rate Card"
2. Version **1.8.0**
3. Click Upgrade

### Step 3: Test with Diagnostic
1. Go to Timesheets
2. Select one timesheet
3. Click "Diagnose (Why Not Linking?)"
4. Should now say: "Simplified matching (no service product required)"
5. Shows what parameters it's searching for

### Step 4: Create Rate Card
Follow the example above - create rate card for your client/employee combo

### Step 5: Link Timesheets
1. Select timesheets
2. Click "Link Rate Cards"
3. Should see: "Linked: X" ✅

### Step 6: Verify
1. Open Rate Card Entry
2. Go to Timesheets tab
3. Should show your timesheets! 🎉

---

## Example Scenarios

### Scenario 1: Simple Setup (Your Case)
**You have**:
- Project: Cheeeeezy Project (customer: Test Company)
- Employee: Administrator
- Many timesheets

**Create 1 rate card**:
- Client: Test Company
- Employee: Administrator
- Rate: $150
- Project: (blank for all projects)

**Result**: ALL timesheets for Administrator on Test Company projects link to this rate card! ✅

### Scenario 2: Project-Specific Rates
**You have**:
- Project A: $150/hour
- Project B: $200/hour
- Same client, same employee

**Create 2 rate cards**:
- RCE001: Client=X, Employee=Y, Project=A, Rate=$150
- RCE002: Client=X, Employee=Y, Project=B, Rate=$200

**Result**: Timesheets match correct rate based on project! ✅

### Scenario 3: Multiple Employees
**You have**:
- Employee: John (senior) → $150/hour
- Employee: Jane (junior) → $100/hour
- Same client, same projects

**Create 2 rate cards**:
- RCE001: Client=X, Employee=John, Rate=$150
- RCE002: Client=X, Employee=Jane, Rate=$100

**Result**: Each employee's timesheets get their own rate! ✅

---

## Frequently Asked Questions

### Q: Do I still need Sales Order Lines?
**A**: Yes, for creating rate cards. But timesheets don't need SO lines to link to rate cards anymore.

### Q: What happens to the service product field?
**A**: It's still there in the rate card entry (for your reference/invoicing), just not required for matching timesheets.

### Q: Can I still have project-specific rates?
**A**: Yes! Set the Project field in rate card for project-specific, or leave blank for client-wide.

### Q: Will my old rate cards still work?
**A**: Yes! No changes needed. They'll match timesheets using the new simplified logic.

### Q: Can one timesheet match multiple rate cards?
**A**: No. The system picks the most specific match (project-specific > client-wide). If multiple match at same level, it errors and asks you to fix the overlap.

---

## Files Changed

1. `models/tm_rate_card_entry.py` - Added `resolve_rate_for_timesheet()` method
2. `models/account_analytic_line.py` - Updated to use simplified matching
3. `__manifest__.py` - Version 1.8.0

---

## Summary

**What changed**: Timesheet matching simplified - service product no longer required
**Why**: Timesheets don't naturally have service products; was blocking linking
**Impact**: Timesheets now link easily based on project, employee, date only
**Version**: 1.8.0 (major feature change)

**Your timesheets should link now!** Create a rate card with your client/employee, then click "Link Rate Cards". 🎉

# Validate vs. Link Rate Cards - What's the Difference?

## Quick Answer

✅ **Use "Validate"** - This is your main workflow (validates timesheets AND links rate cards)
⚠️ **Use "Link Rate Cards"** - Only for bulk-fixing old timesheets

---

## The Two Buttons Explained

### 1. "Validate" Button (Main Workflow)

**Where**: Timesheets → My Timesheets (or grid view if timesheet_grid module installed)

**What it does**:
1. ✅ Marks timesheets as **validated/approved** (from timesheet_grid module)
2. ✅ **Automatically links rate cards** (our new feature!)
3. ✅ Sets billing rates
4. ✅ Calculates billable amounts
5. ✅ Locks timesheets (prevents further editing)

**When to use**:
- End of week/period when you review and approve timesheets
- After employees submit their timesheets
- When you're ready to mark time as billable

**Example workflow**:
```
Monday-Friday: Employees log hours
    ↓
Friday afternoon: You review timesheets
    ↓
Click "Validate" on timesheets
    ↓
✅ Timesheets validated
✅ Rate cards linked automatically
✅ Ready for invoicing
```

---

### 2. "Link Rate Cards" Button (Manual Bulk Action)

**Where**: Timesheets → My Timesheets → Select timesheets → Actions dropdown (or header button)

**What it does**:
1. Finds matching rate card for each selected timesheet
2. Links timesheet to rate card
3. Sets billing rate
4. Calculates billable amount
5. **Does NOT validate/approve** the timesheets

**When to use**:
- After upgrading the module (to link old timesheets)
- If rate cards were missing when validated, now you've created them
- Bulk-processing historical data
- Troubleshooting/fixing timesheet links

**Example scenario**:
```
Problem: Upgraded module, have 1000 old validated timesheets
Solution:
1. Go to Timesheets
2. Filter: "Validated" + "Rate Card = Not Set"
3. Select All
4. Click "Link Rate Cards"
5. Done! All old timesheets now linked
```

---

## Recommended Workflow

### Normal Day-to-Day (Simple!)

1. **Employees log time** throughout the week
2. **End of period** → You review timesheets
3. **Click "Validate"** → Done! ✅
   - Timesheets approved
   - Rate cards linked automatically
   - Ready to bill

That's it! You **don't need** the "Link Rate Cards" button in normal use.

---

## When Rate Cards Get Linked

### Automatic Linking (You don't do anything)

Rate cards link automatically:
- ✅ When you **create** a new timesheet
- ✅ When you **edit** a timesheet (if key fields change)
- ✅ When you **validate** timesheets

### Manual Linking (You click "Link Rate Cards")

Only needed for:
- ⚠️ Old timesheets from before module was installed
- ⚠️ Timesheets where rate card was missing initially
- ⚠️ Bulk corrections/troubleshooting

---

## What "Validate" Does (Step by Step)

When you click "Validate" on timesheets:

1. **Validation** (from timesheet_grid module):
   - Sets `validated = True`
   - Locks timesheet (read-only)
   - Updates employee's last validated date
   - Shows as "Validated" in views

2. **Rate Card Linking** (from tm_rate_card module):
   - Searches for matching rate card:
     - Same client
     - Same employee
     - Same service product
     - Valid for this date
   - Links timesheet to rate card
   - Sets `tm_billing_rate` from rate card
   - Calculates `tm_billable_amount` (hours × rate)
   - Updates rate card statistics

3. **Result**:
   - ✅ Timesheet approved and locked
   - ✅ Billing rate assigned
   - ✅ Ready for invoicing
   - ✅ Visible in Rate Card Entry stats

---

## Visual Comparison

### Using "Validate" (Correct Way)

```
Timesheets Created (Draft)
    ↓
Review & Click "Validate"
    ↓
✅ Status: Validated
✅ Rate Card: Linked
✅ Billing Rate: Set
✅ Billable Amount: Calculated
    ↓
Ready to Invoice
```

### Using Only "Link Rate Cards" (Wrong Way)

```
Timesheets Created (Draft)
    ↓
Click "Link Rate Cards" only
    ↓
⚠️ Status: Still Draft
✅ Rate Card: Linked
✅ Billing Rate: Set
✅ Billable Amount: Calculated
    ↓
NOT VALIDATED! Not ready to invoice!
```

---

## Common Scenarios

### Scenario 1: Normal Weekly Workflow
**Do**: Click "Validate" at end of week
**Don't**: Use "Link Rate Cards"
**Why**: Validate does everything you need

### Scenario 2: Just Upgraded Module
**Do**: Use "Link Rate Cards" once for old timesheets
**Then**: Use "Validate" for new timesheets going forward

### Scenario 3: Rate Card Was Missing
**Situation**: You validated timesheets but rate card didn't exist yet
**Fix**:
1. Create the missing rate card
2. Find the timesheets (already validated)
3. Use "Link Rate Cards" to link them
**Result**: Now they're both validated AND linked

### Scenario 4: Wrong Rate Card Linked
**Fix**:
1. Select the timesheets
2. Click "Link Rate Cards" again
3. It will re-link to correct rate card

---

## Checking If It Worked

### After Clicking "Validate":

**In Timesheet List:**
- Status: "Validated" ✅
- Rate Card Entry: RCE00001 ✅
- Billing Rate: $150.00 ✅
- Billable Amount: $1,200.00 ✅

**In Rate Card Entry (Timesheets Tab):**
- Timesheet Count: Increased ✅
- Total Hours: Updated ✅
- Total Amount: Updated ✅
- Your timesheets appear in list ✅

---

## Troubleshooting

### "Validate" button doesn't link rate cards
**Cause**: Module not upgraded properly
**Fix**:
1. Restart Odoo
2. Upgrade tm_rate_card module to v1.7.0
3. Try again

### "Link Rate Cards" button not visible
**Cause**: User doesn't have permissions
**Fix**: Add user to "Rate Card Manager" group

### Rate card not linking when validated
**Cause**: No matching rate card exists
**Check**:
- Does rate card exist for this client?
- Does it match the employee?
- Is the date within the effective range?
**Fix**: Create missing rate card, then re-link

### Validated but no billing rate
**Cause**: Rate card couldn't be found
**Fix**:
1. Create the rate card
2. Select the timesheet
3. Click "Link Rate Cards"

---

## Best Practices

### ✅ Do This:
- Use "Validate" as your standard workflow
- Link rate cards automatically by validating
- Only use "Link Rate Cards" for special cases
- Create rate cards BEFORE validating timesheets

### ❌ Don't Do This:
- Don't use "Link Rate Cards" instead of "Validate"
- Don't skip validation just to link rate cards
- Don't validate timesheets if rate cards don't exist yet (create them first)

---

## Summary

| Button | Purpose | When to Use | What it Does |
|--------|---------|-------------|--------------|
| **Validate** | Main workflow | End of period | Validates timesheets + Links rate cards |
| **Link Rate Cards** | Bulk fixing | After upgrade / Special cases | Links rate cards only (no validation) |

**Remember**:
- 👍 **"Validate" = Your main button** (does everything)
- 🔧 **"Link Rate Cards" = Maintenance tool** (special cases only)

---

## Still Confused?

**Simple rule**:
- If timesheets are new → Click **"Validate"**
- If timesheets are old (already validated) → Click **"Link Rate Cards"**

That's it! 🎉

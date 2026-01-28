# Rate Card Module v1.5.0 - Client Auto-Fill from Sales Order

**Date**: 2026-01-28
**Version**: 1.5.0 (feature release)

## Major Change: Client Field Now Auto-Filled

Changed the workflow so that **Client is automatically taken from the Sales Order** instead of being manually selected.

### What Changed

#### Before (v1.4.0):
```
Workflow:
1. Select Client (manual)
2. Select Sales Order (filtered by client)
3. Select Sales Order Line
4. Service Product auto-fills
```

#### After (v1.5.0):
```
Workflow:
1. Select Sales Order (first)
2. Client auto-fills from Sales Order (readonly)
3. Select Sales Order Line
4. Service Product auto-fills
```

---

## Benefits

✅ **Simpler workflow** - One less field to fill manually
✅ **Data consistency** - Client always matches the Sales Order
✅ **No mistakes** - Cannot select wrong client for a Sales Order
✅ **Faster entry** - Auto-fill reduces manual work
✅ **Cleaner UI** - Logical field order (SO → Client → SO Line)

---

## Changes Made

### 1. **Client Field Made Computed**
   - Changed from manual selection to computed field
   - Now readonly, automatically filled from `sale_order_id.partner_id`
   - Added `_compute_client_id()` method
   - **File**: `models/tm_rate_card_entry.py:67-73, 202-212`

### 2. **Sales Order Made Required**
   - `sale_order_id` is now required (was optional)
   - Client depends on it, so it must be selected first
   - **File**: `models/tm_rate_card_entry.py:104-109`

### 3. **Updated Onchange Methods**
   - Removed manual client assignment from onchange methods
   - Client now auto-computes via dependency chain
   - **File**: `models/tm_rate_card_entry.py:252-270`

### 4. **Reordered Form View Fields**
   - Sales Order moved to top (select first)
   - Client shown second (readonly, auto-filled)
   - Logical flow: SO → Client → Project → SO Line → Product
   - **File**: `views/tm_rate_card_entry_views.xml:99-110`

### 5. **Updated Validation**
   - Added check for `sale_order_id` in constraints
   - Added check that client is filled from SO
   - Better error messages
   - **File**: `models/tm_rate_card_entry.py:284-303`

---

## Technical Details

### Field Definition Changes

**Before:**
```python
client_id = fields.Many2one(
    comodel_name='res.partner',
    string='Client',
    required=True,
    index=True,
    help="Customer for whom this rate applies",
)
```

**After:**
```python
client_id = fields.Many2one(
    comodel_name='res.partner',
    string='Client',
    compute='_compute_client_id',
    store=True,
    readonly=True,
    index=True,
    help="Customer from the selected Sales Order",
)
```

### Compute Method

```python
@api.depends('sale_order_id', 'sale_order_id.partner_id')
def _compute_client_id(self):
    """Compute client from the selected Sales Order"""
    for entry in self:
        if entry.sale_order_id and entry.sale_order_id.partner_id:
            entry.client_id = entry.sale_order_id.partner_id
        else:
            entry.client_id = False
```

### Dependency Chain

```
sale_order_id (user selects)
    ↓
client_id (auto-computed from SO partner)
    ↓
Used in constraints, views, name computation
```

---

## Form View - New Field Order

```
┌─────────────────────────────────────────────┐
│ Reference: RCE00001                         │
│ Name: [Auto-generated]                      │
├─────────────────────────────────────────────┤
│ Dimensions:                                 │
│                                             │
│ Company: My Company                         │
│ Sales Order: SO001 ▼ [Select first]        │
│ Client: Customer A [Auto-filled, readonly] │
│ Project: Project X ▼                        │
│ Sales Order Line: Line 1 ▼                  │
│ Service Product: Dev Hour [Auto, readonly]  │
│ Employee: John Doe ▼                        │
└─────────────────────────────────────────────┘
```

---

## Upgrade Instructions

### ⚠️ IMPORTANT: Existing Data

**Existing rate card entries may need attention:**

- Entries with `sale_order_id` set: Client will auto-compute ✅
- Entries without `sale_order_id`: Need to be updated or deleted ⚠️

### Step 1: Check Existing Entries

**Before upgrading**, check for entries without a Sales Order:

```python
# In Odoo Python console
entries_without_so = env['tm.rate.card.entry'].search([
    ('sale_order_id', '=', False)
])

print(f"Found {len(entries_without_so)} entries without Sales Order:")
for entry in entries_without_so:
    print(f"  - RCE{entry.id}: {entry.client_id.name}")
```

### Step 2: Handle Problematic Entries

**Option A: Delete them** (if they're old/unused):
```python
entries_without_so.unlink()
```

**Option B: Find matching Sales Orders** (recommended):
```python
for entry in entries_without_so:
    # Try to find a sales order for this client
    so = env['sale.order'].search([
        ('partner_id', '=', entry.client_id.id)
    ], limit=1)

    if so:
        entry.write({'sale_order_id': so.id})
        print(f"Linked entry {entry.id} to SO {so.name}")
    else:
        print(f"WARNING: No SO found for entry {entry.id}")
```

### Step 3: Restart Odoo

```bash
sudo systemctl restart odoo
```

### Step 4: Upgrade Module

1. Go to **Apps** menu
2. Remove "Apps" filter
3. Search: **Rate Card**
4. Verify version shows **1.5.0**
5. Click **Upgrade**

### Step 5: Verify

1. Check existing entries - client should be populated
2. Create new entry:
   - Select Sales Order first
   - Client should auto-fill
   - Client field should be readonly (grayed out)
3. Try changing Sales Order - client should update automatically

---

## New User Workflow

### Creating a Rate Card Entry (v1.5.0)

1. **Click Create** in Rate Card Entries
2. **Select Sales Order** (required, first field)
   - As soon as you select it, **Client auto-fills** ✅
3. **Select Project** (optional)
4. **Select Sales Order Line** (required)
   - Dropdown shows only lines from selected SO
   - As soon as you select it, **Service Product auto-fills** ✅
5. **Select Employee** (required)
6. **Fill Rate, Dates, etc.**
7. **Save**
8. **Reference number auto-generates** (e.g., RCE00001) ✅

### What You Cannot Do Anymore

❌ Manually select or change Client
- Client is always tied to Sales Order
- To change client, change the Sales Order

---

## Migration Impact

### Low Risk Scenarios ✅
- All existing entries have `sale_order_id` set
- Sales Orders all have valid `partner_id`
- No orphaned or incomplete entries

### Medium Risk Scenarios ⚠️
- Some entries missing `sale_order_id`
- Need to link them to Sales Orders before upgrade
- Use migration script provided above

### High Risk Scenarios 🚨
- Many entries without Sales Orders
- Complex data cleanup needed
- Consider creating placeholder Sales Orders

---

## Rollback (If Needed)

If this change causes problems:

```bash
# Restore database backup
psql your_database < backup_before_v1.5.0.sql

# Revert code to v1.4.0
cd jito_modules/tm_rate_card
git checkout v1.4.0  # or manually restore files
```

Then restart Odoo and downgrade module.

---

## Testing Checklist

After upgrade, verify:

- [ ] Existing entries show client (auto-computed from SO)
- [ ] Client field is readonly (cannot edit)
- [ ] Creating new entry: can select Sales Order
- [ ] After selecting SO, client auto-fills
- [ ] Changing SO updates client automatically
- [ ] Cannot save without Sales Order
- [ ] Sales Order Line dropdown filters by selected SO
- [ ] Service Product auto-fills from SO Line
- [ ] Reference number still generates (RCE00001, etc.)
- [ ] Tree view shows client correctly
- [ ] Search by client still works

---

## Troubleshooting

### Issue: "Sales Order is required" error

**Cause**: Trying to save without selecting a Sales Order

**Fix**: Select a Sales Order first (it's now required)

### Issue: Client field is empty

**Cause**: Selected Sales Order has no customer

**Fix**:
1. Open the Sales Order
2. Set the Customer field
3. Return to rate card entry
4. Re-select the Sales Order

### Issue: Cannot change client

**Cause**: Client is now readonly (auto-computed)

**Fix**: This is expected behavior. To change client:
1. Change the Sales Order to one with a different customer
2. Or create a new rate card entry with a different SO

### Issue: Existing entries have wrong client

**Cause**: Client was set manually before, now computed from SO

**Fix**:
```python
# Update specific entry
entry = env['tm.rate.card.entry'].browse(123)
entry._compute_client_id()  # Force recompute
```

---

## API / Integration Impact

### For External Integrations

**Breaking Change**: ⚠️
- Cannot set `client_id` directly via API anymore
- Must set `sale_order_id` instead
- `client_id` will auto-compute

**Before (v1.4.0):**
```python
entry = env['tm.rate.card.entry'].create({
    'client_id': 42,
    'sale_order_id': 100,
    'employee_id': 5,
    # ...
})
```

**After (v1.5.0):**
```python
entry = env['tm.rate.card.entry'].create({
    # client_id removed - will auto-compute
    'sale_order_id': 100,  # Required! Client computes from this
    'employee_id': 5,
    # ...
})
```

### For Imports / Data Loading

Update your import scripts to:
1. Remove `client_id` from import data
2. Ensure `sale_order_id` is always provided
3. Client will populate automatically

---

## Files Changed

1. `__manifest__.py` - Version bump to 1.5.0
2. `models/tm_rate_card_entry.py` - Client field changed to computed, SO made required
3. `views/tm_rate_card_entry_views.xml` - Field order changed, client marked readonly

---

## Summary

**What changed**: Client is now auto-filled from Sales Order
**Why**: Simpler workflow, better data consistency
**Impact**: Sales Order now required; existing entries need SO set
**Version**: 1.5.0 (feature release)

This change makes rate card entry faster and eliminates the possibility of mismatched client/sales order data.

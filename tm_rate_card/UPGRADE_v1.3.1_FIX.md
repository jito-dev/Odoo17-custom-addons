# Rate Card Module v1.3.1 - Fix for Mandatory Field Error

**Date**: 2026-01-28
**Version**: 1.3.1 (hotfix for 1.3.0)

## Issue Fixed

**Error**: "The operation cannot be completed: a mandatory field is not set - Field: Service Product (service_product_id)"

### Root Cause
- `sale_order_line_id` was marked as `required=True` at model level
- `service_product_id` is a computed field that depends on `sale_order_line_id`
- When creating new records, Odoo tries to validate before the computed field is calculated
- This created a chicken-and-egg problem during form filling

---

## Changes Made

### 1. **Removed Model-Level Required Constraint**
   - Changed `sale_order_line_id` from `required=True` to optional at model level
   - **File**: `models/tm_rate_card_entry.py:98-103`

### 2. **Added View-Level Required Attribute**
   - Added `required="1"` to the view so UI still shows the field as required
   - Users still see the red asterisk (*) indicating it's mandatory
   - **File**: `views/tm_rate_card_entry_views.xml:100`

### 3. **Added Validation Constraint**
   - Added new `_check_required_fields()` constraint
   - Validates both `sale_order_line_id` and `service_product_id` are set when saving
   - Provides clear error messages if either field is missing
   - **File**: `models/tm_rate_card_entry.py:269-280`

### 4. **Added force_save to Service Product**
   - Added `force_save="1"` to ensure computed value is persisted
   - **File**: `views/tm_rate_card_entry_views.xml:102`

---

## Before Upgrading - Check for Problematic Records

If you have **existing rate card entries** in your database, you need to check if any are missing `sale_order_line_id`.

### Option 1: Check via Odoo UI
1. Go to **Rate Cards → Rate Card Entries**
2. Add filter: **Sales Order Line is not set**
3. Review these entries - they will fail validation after upgrade
4. Either delete them or link them to appropriate sales order lines

### Option 2: Check via Python (Developer Mode)
In Odoo's debug/developer console, run:

```python
# Check for entries without sale_order_line_id
problematic_entries = env['tm.rate.card.entry'].search([
    ('sale_order_line_id', '=', False)
])

print(f"Found {len(problematic_entries)} entries without Sales Order Line:")
for entry in problematic_entries:
    print(f"  - ID {entry.id}: {entry.name}")
```

### Option 3: Check via SQL
```sql
SELECT id, name, client_id, employee_id
FROM tm_rate_card_entry
WHERE sale_order_line_id IS NULL;
```

---

## Upgrade Steps

### Step 1: Backup Database
```bash
# Always backup before upgrading!
pg_dump your_database > backup_before_rate_card_upgrade.sql
```

### Step 2: Handle Existing Records

**If you found problematic entries**, do ONE of the following:

**Option A: Delete them (if they're draft/unused)**
```python
env['tm.rate.card.entry'].search([
    ('sale_order_line_id', '=', False),
    ('state', '=', 'draft')
]).unlink()
```

**Option B: Link them to sales orders (if they should be kept)**
- Manually edit each entry in the UI
- Select appropriate Sales Order and Sales Order Line
- Save

### Step 3: Upgrade Module
1. Restart Odoo service (to load new code)
2. Go to **Apps** menu
3. Remove "Apps" filter
4. Search for "Rate Card"
5. Click **Upgrade** button

### Step 4: Test
1. Try creating a new rate card entry
2. Verify you can:
   - Select Sales Order
   - Select Sales Order Line
   - Service Product auto-fills
   - Save without errors

---

## Technical Details

### New Constraint Code
```python
@api.constrains('sale_order_line_id', 'service_product_id')
def _check_required_fields(self):
    """Ensure sales order line and service product are set"""
    for entry in self:
        if not entry.sale_order_line_id:
            raise ValidationError(
                _("Sales Order Line is required. Please select a sales order line for this rate card entry.")
            )
        if not entry.service_product_id:
            raise ValidationError(
                _("Service Product is required. It should be automatically filled from the Sales Order Line. "
                  "Please ensure the selected Sales Order Line has a product.")
            )
```

### Field Changes
**Before (v1.3.0)**:
```python
sale_order_line_id = fields.Many2one(
    comodel_name='sale.order.line',
    string='Sales Order Line',
    required=True,  # <-- Problem!
    ...
)
```

**After (v1.3.1)**:
```python
sale_order_line_id = fields.Many2one(
    comodel_name='sale.order.line',
    string='Sales Order Line',
    # No required=True at model level
    ...
)
```

With view enforcement:
```xml
<field name="sale_order_line_id"
       required="1"  <!-- UI shows as required -->
       ... />
```

---

## Why This Approach Works

1. **Model Level**: Field is optional, allowing form to be filled step-by-step
2. **View Level**: Field appears as required (red asterisk) in UI
3. **Constraint Level**: Validation happens when saving, ensuring data integrity
4. **Computed Field**: `service_product_id` can compute safely after `sale_order_line_id` is set

This follows Odoo best practices for handling computed fields that depend on required fields.

---

## Troubleshooting

### Error: "Sales Order Line is required"
- **Cause**: Trying to save without selecting a sales order line
- **Fix**: Select a sales order line before saving

### Error: "Service Product is required"
- **Cause**: Selected sales order line has no product
- **Fix**: Select a different sales order line that has a product

### Error: Still getting "mandatory field not set"
- **Cause**: Module code not fully reloaded
- **Fix**:
  1. Restart Odoo service completely
  2. Clear browser cache
  3. Try upgrading module again

---

## Rollback (If Needed)

If upgrade causes issues and you need to rollback:

```bash
# Restore database backup
psql your_database < backup_before_rate_card_upgrade.sql

# Revert code changes (if using git)
cd jito_modules/tm_rate_card
git checkout v1.2.0  # or previous version tag
```

Then restart Odoo and downgrade module in Apps menu.

---

## Summary

✅ **Fixed**: Mandatory field validation error
✅ **Method**: Moved required constraint from model to view + added explicit validation
✅ **Impact**: Forms can now be filled without validation errors
✅ **Breaking**: Existing records without `sale_order_line_id` will fail - must be cleaned up first

The module now properly handles the computed field dependency while maintaining data integrity.

# Rate Card Module v1.3.0 Update Notes

**Date**: 2026-01-28
**Version**: 1.3.0 (upgraded from 1.2.0)

## Summary of Changes

This update addresses field visibility, data flow improvements, and menu accessibility issues.

---

## Changes Made

### 1. **Client Field (`client_id`) - Fixed Contact Selection**
   - **Issue**: Field had restrictive domain that prevented showing all contacts
   - **Fix**: Removed `domain="[('customer_rank', '>', 0)]"` to show all contacts from Contacts module (res.partner)
   - **Impact**: Users can now select any contact as a client
   - **File**: `models/tm_rate_card_entry.py:55-61`

### 2. **Sales Order Field (`sale_order_id`) - Fixed Order Listing**
   - **Issue**: View domain restricted to only confirmed/done orders
   - **Fix**: Removed `domain="[('partner_id', '=', client_id), ('state', 'in', ['sale', 'done'])]"` from view
   - **Impact**: All sales orders for the selected client now appear in dropdown
   - **File**: `views/tm_rate_card_entry_views.xml:107`

### 3. **Sales Order Line Field (`sale_order_line_id`) - Made Required & Dynamic**
   - **Changes**:
     - Made field **required** (was optional)
     - Updated view domain to `[('order_id', '=', sale_order_id)]` for dynamic filtering
     - Removed restrictive model-level domain
   - **Impact**:
     - Sales order line selection is now mandatory
     - Lines update dynamically when sales order is selected
   - **Files**:
     - `models/tm_rate_card_entry.py:97-103`
     - `views/tm_rate_card_entry_views.xml:100-101`

### 4. **Service Product Field (`service_product_id`) - Made Computed**
   - **Changes**:
     - Converted from manual selection to **computed field**
     - Now automatically populated from `sale_order_line_id.product_id`
     - Field is **readonly** in views
     - Added compute method `_compute_service_product_id()`
   - **Impact**:
     - Users no longer manually select service product
     - Service product automatically comes from the selected SO line
     - Ensures data consistency between SO line and rate card
   - **Files**:
     - `models/tm_rate_card_entry.py:64-70` (field definition)
     - `models/tm_rate_card_entry.py:189-195` (compute method)
     - `models/tm_rate_card_entry.py:221-233` (updated onchange - removed manual assignment)
     - `views/tm_rate_card_entry_views.xml:102` (made readonly in view)

### 5. **Menu Visibility - Fixed**
   - **Issues Fixed**:
     - Removed missing icon reference (`web_icon="tm_rate_card,static/description/icon.png"`)
     - Restructured menu to make "Rate Card Entries" visible to all viewers
     - Moved "Rate Card Entries" from under "Configuration" to directly under root menu
   - **Impact**:
     - Rate Card module now appears in Odoo menu
     - Both viewers and managers can access Rate Card Entries
     - Configuration submenu reserved for future admin settings
   - **File**: `views/tm_rate_card_menus.xml:9-28`

---

## Data Model Impact

### New Field Dependencies
- `service_product_id` now depends on `sale_order_line_id.product_id`
- Creating/editing rate card entries **requires** a sales order line to be selected first

### Workflow Changes
1. Select **Client** (any contact)
2. Select **Sales Order** (any order for that client)
3. Select **Sales Order Line** (lines from selected order)
4. **Service Product** auto-fills from selected line
5. Continue with other fields (employee, dates, rate, etc.)

---

## Migration Notes

### For Existing Data
- **WARNING**: Existing rate card entries without `sale_order_line_id` will now be **invalid**
- Before upgrading, you should either:
  1. Delete draft entries without SO lines, OR
  2. Update existing entries to link to appropriate SO lines

### Recommended Pre-Upgrade Actions
```python
# Check for entries without SO line
entries_without_so_line = self.env['tm.rate.card.entry'].search([
    ('sale_order_line_id', '=', False)
])
# Review and update or delete these entries
```

---

## Testing Checklist

After module upgrade, test the following:

1. **Menu Visibility**
   - [ ] "Rate Cards" menu appears in main Odoo menu
   - [ ] "Rate Card Entries" submenu is accessible
   - [ ] Users with viewer role can see the menu

2. **Client Selection**
   - [ ] All contacts appear in Client dropdown
   - [ ] Can select any contact (not just customers)

3. **Sales Order Selection**
   - [ ] All sales orders appear (not just confirmed ones)
   - [ ] Sales orders filter by selected client

4. **Sales Order Line Selection**
   - [ ] Sales order lines appear in dropdown
   - [ ] Lines update when sales order changes
   - [ ] Only lines from selected SO appear

5. **Service Product Auto-Fill**
   - [ ] Service product auto-fills when SO line is selected
   - [ ] Service product field is readonly (cannot manually change)
   - [ ] Service product matches the product from SO line

6. **Form Validation**
   - [ ] Cannot save entry without sales order line
   - [ ] Validation errors are clear and helpful

---

## Technical Details

### Modified Files
1. `__manifest__.py` - Version bump to 1.3.0
2. `models/tm_rate_card_entry.py` - Field changes and compute method
3. `views/tm_rate_card_entry_views.xml` - View updates for new field behavior
4. `views/tm_rate_card_menus.xml` - Menu restructure

### New Compute Method
```python
@api.depends('sale_order_line_id', 'sale_order_line_id.product_id')
def _compute_service_product_id(self):
    """Compute service product from the selected Sales Order Line"""
    for entry in self:
        if entry.sale_order_line_id and entry.sale_order_line_id.product_id:
            entry.service_product_id = entry.sale_order_line_id.product_id
        else:
            entry.service_product_id = False
```

---

## Upgrade Instructions

1. **Backup your database** before upgrading
2. Stop Odoo service
3. Update module files
4. Restart Odoo service
5. Go to **Apps** menu
6. Remove "Apps" filter, search for "Rate Card"
7. Click **Upgrade** button on "Rate Card Management (Pricing Authority)"
8. Verify menu appears and test functionality per checklist above
9. Assign users to "Rate Card Viewer" or "Rate Card Manager" groups if not already assigned

---

## Known Limitations

1. **Sales Order Line is now mandatory** - All rate card entries must be linked to a specific SO line
2. **Service Product cannot be manually overridden** - It always comes from the SO line
3. **Existing entries without SO line will need manual correction** after upgrade

---

## Support

For issues or questions, refer to module guidance documents:
- `GUIDANCE.md` - Overall module architecture
- `README.md` - User documentation
- `IMPLEMENTATION_SUMMARY.md` - Technical implementation details

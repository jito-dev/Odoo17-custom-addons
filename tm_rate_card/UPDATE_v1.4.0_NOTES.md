# Rate Card Module v1.4.0 - Reference/Sequence Number Feature

**Date**: 2026-01-28
**Version**: 1.4.0 (feature release)

## New Feature: Reference Numbers

Added automatic reference/sequence numbering for rate card entries, similar to Sales Orders.

### What's New

✅ **Auto-generated reference numbers** in format `RCE00001`, `RCE00002`, etc.
- **RCE** = Rate Card Entry
- **5-digit padding** with leading zeros
- **Unique per entry**, auto-incremented

✅ **Visible everywhere**:
- Tree view (first column, bold)
- Form view (large header field)
- Search/filter by reference
- Can be used as internal company reference

✅ **Read-only and permanent**:
- Cannot be edited manually
- Generated on creation
- Never changes
- Not copied when duplicating entries

---

## Changes Made

### 1. **New Reference Field**
   - Added `reference` field to model
   - Auto-populated on creation with next sequence number
   - Default: 'New' (replaced with actual number on save)
   - **File**: `models/tm_rate_card_entry.py:32-40`

### 2. **Sequence Definition**
   - Created `ir.sequence` record for generating numbers
   - Prefix: `RCE`
   - Padding: 5 digits (00001, 00002, etc.)
   - Company-independent (works across all companies)
   - **File**: `data/tm_rate_card_sequence.xml`

### 3. **Auto-generation Logic**
   - Overridden `create()` method to assign sequence
   - Similar pattern to Sales Orders
   - **File**: `models/tm_rate_card_entry.py:410-426`

### 4. **View Updates**
   - **Tree view**: Added reference as first column (bold)
   - **Form view**: Added reference as main header (H1)
   - **Search view**: Added reference to searchable fields
   - **Files**: `views/tm_rate_card_entry_views.xml`

### 5. **Search Enhancement**
   - Added `_rec_names_search = ['reference', 'name']`
   - Users can search by reference number in dropdowns/lookups
   - **File**: `models/tm_rate_card_entry.py:25`

---

## Before and After

### Before (v1.3.2):
```
Rate Card Entry view:
[No reference number]
Name: Client A / Project X / Service / Employee [dates]
```

### After (v1.4.0):
```
Rate Card Entry view:
Reference: RCE00001
Name: Client A / Project X / Service / Employee [dates]
```

### Tree View Before:
```
| Client | Project | Service | Employee | Rate | ...
```

### Tree View After:
```
| Reference | Client | Project | Service | Employee | Rate | ...
| RCE00001  | ...    | ...     | ...     | ...      | ... | ...
```

---

## Upgrade Instructions

### Step 1: Backup Database
```bash
pg_dump your_database > backup_before_v1.4.0.sql
```

### Step 2: Restart Odoo
```bash
sudo systemctl restart odoo
```

### Step 3: Upgrade Module
1. Go to **Apps** menu
2. Remove "Apps" filter
3. Search: **Rate Card**
4. Verify version shows **1.4.0**
5. Click **Upgrade**
6. Wait for completion

### Step 4: Verify Sequence Installation
After upgrade, check that the sequence was created:
1. Go to **Settings → Technical → Sequences & Identifiers → Sequences**
2. Search for: **Rate Card Entry Sequence**
3. Should show:
   - Code: `tm.rate.card.entry`
   - Prefix: `RCE`
   - Padding: 5
   - Next Number: 1

### Step 5: Test New Entries
1. Go to **Rate Cards → Rate Card Entries**
2. Create a new entry
3. **Reference field should auto-fill with RCE00001**
4. Save the entry
5. Create another entry
6. Should get **RCE00002**

---

## Existing Data Handling

### What Happens to Existing Entries?

**Existing rate card entries will get reference numbers assigned** during upgrade:

- The upgrade process does NOT automatically assign references to existing records
- Existing entries will have `reference = 'New'` until updated
- **Recommended**: Run a migration script to assign references to existing entries

### Migration Script (Optional but Recommended)

Run this in Odoo's Python console after upgrade:

```python
# Assign reference numbers to existing entries without one
entries = env['tm.rate.card.entry'].search([
    ('reference', '=', 'New')
], order='create_date asc, id asc')

for entry in entries:
    # This will trigger the sequence generation
    new_ref = env['ir.sequence'].next_by_code('tm.rate.card.entry') or 'New'
    entry.write({'reference': new_ref})
    env.cr.commit()  # Commit each update

print(f"Updated {len(entries)} entries with reference numbers")
```

**Or via SQL** (if you prefer):
```sql
-- WARNING: Only use if comfortable with SQL
UPDATE tm_rate_card_entry
SET reference = 'RCE' || LPAD(ROW_NUMBER() OVER (ORDER BY create_date, id)::TEXT, 5, '0')
WHERE reference = 'New';
```

---

## Technical Details

### Sequence Configuration

```xml
<record id="seq_tm_rate_card_entry" model="ir.sequence">
    <field name="name">Rate Card Entry Sequence</field>
    <field name="code">tm.rate.card.entry</field>
    <field name="prefix">RCE</field>
    <field name="padding">5</field>
    <field name="company_id" eval="False"/>
    <field name="number_increment">1</field>
</record>
```

**Configuration Explained**:
- `code`: Internal identifier used to get next number
- `prefix`: "RCE" prepended to all numbers
- `padding`: 5 digits with leading zeros (00001, 00002)
- `company_id = False`: Sequence shared across companies (not company-specific)
- `number_increment`: Increases by 1 each time

### Field Definition

```python
reference = fields.Char(
    string='Reference',
    required=True,
    copy=False,          # Don't copy when duplicating
    readonly=True,       # Cannot edit manually
    index=True,          # Indexed for fast lookups
    default=lambda self: _('New'),
    help="Unique reference number (e.g., RCE00001)",
)
```

### Create Override

```python
@api.model_create_multi
def create(self, vals_list):
    for vals in vals_list:
        if vals.get('reference', _('New')) == _('New'):
            vals['reference'] = self.env['ir.sequence'].next_by_code(
                'tm.rate.card.entry') or _('New')
    return super().create(vals_list)
```

**Pattern follows Odoo 17 best practices** (same as sale.order)

---

## Benefits

### For Users:
- ✅ Easy to reference specific rate cards in conversations ("Check RCE00015")
- ✅ Quick lookup by number
- ✅ Professional numbering for documentation
- ✅ Clear identification in reports

### For Integrations:
- ✅ Stable reference that never changes
- ✅ Can be used in external systems
- ✅ Better for linking/reporting
- ✅ Easier troubleshooting

### For Auditing:
- ✅ Chronological numbering shows creation order
- ✅ Gaps indicate deleted entries
- ✅ Sequence number = audit trail

---

## Customization Options

### Change Prefix
Edit the sequence record:
1. Go to **Settings → Technical → Sequences**
2. Find "Rate Card Entry Sequence"
3. Change `Prefix` from `RCE` to your desired prefix (e.g., `RC`, `RATE`, etc.)

### Change Padding
1. Same as above
2. Change `Padding` to desired number of digits (3 = 001, 4 = 0001, etc.)

### Company-Specific Sequences
If you want separate sequences per company:
1. Edit sequence record
2. Set `company_id` to specific company
3. Create duplicate sequences for other companies

### Reset/Change Starting Number
1. Go to sequence record
2. Change `Next Number` field
3. Future entries will start from that number

---

## Testing Checklist

After upgrade, verify:

- [ ] New entries get reference numbers (RCE00001, RCE00002, etc.)
- [ ] Reference appears in tree view (first column, bold)
- [ ] Reference appears in form view (main header)
- [ ] Can search by reference number
- [ ] Reference is read-only (cannot edit)
- [ ] Duplicating entry generates new reference (doesn't copy)
- [ ] Reference doesn't change after creation
- [ ] Existing entries either have 'New' or assigned references

---

## Troubleshooting

### Issue: New entries show "New" instead of RCE00001

**Cause**: Sequence not created or not accessible

**Fix**:
1. Check sequence exists: Settings → Technical → Sequences
2. If missing, manually create:
   - Code: `tm.rate.card.entry`
   - Prefix: `RCE`
   - Padding: 5
3. Restart Odoo and try again

### Issue: Sequence skips numbers

**Cause**: Normal behavior (Odoo pre-allocates sequence numbers for performance)

**Fix**: This is expected - sequence numbers may have gaps, which is fine

### Issue: Existing entries still show "New"

**Cause**: References not assigned during upgrade

**Fix**: Run the migration script provided above to assign references

### Issue: Duplicate reference numbers

**Cause**: Multiple sequences or manual data changes

**Fix**:
1. Check only one sequence exists with code `tm.rate.card.entry`
2. Check for manual SQL changes
3. May need to reset sequence and reassign

---

## Files Changed

1. `__manifest__.py` - Version bump + added data file
2. `data/tm_rate_card_sequence.xml` - NEW: Sequence definition
3. `models/tm_rate_card_entry.py` - Added reference field + create override
4. `views/tm_rate_card_entry_views.xml` - Added reference to tree/form/search views

---

## Summary

**What was added**: Auto-generated reference numbers (RCE00001, RCE00002, etc.)
**Why**: Professional identification, easy lookup, stable references
**Impact**: All new entries get reference; existing entries need migration
**Version**: 1.4.0 (feature release)

This feature makes rate card entries easier to identify, reference, and track throughout their lifecycle.

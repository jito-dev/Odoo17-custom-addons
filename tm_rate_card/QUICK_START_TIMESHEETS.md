# Quick Start - Timesheet Tracking in Rate Cards

## What's New in v1.6.0

✅ **View timesheets** from Rate Card Entry
✅ **See hours tracked** and billable amounts
✅ **Monitor usage** of each rate card

---

## How to Use

### View Timesheets for a Rate Card

1. Go to **Rate Cards → Rate Card Entries**
2. Open any Rate Card Entry
3. Click **"Timesheets" tab**
4. See:
   - **Statistics**: Total count, hours, amount
   - **List**: All timesheet entries using this rate

### What You'll See

```
Statistics Summary:
├─ Timesheet Count: 45
├─ Total Hours: 180.5 hours
└─ Total Billable Amount: $27,075.00

Timesheet List:
| Date   | Employee | Project | Hours | Rate    | Billable  |
|--------|----------|---------|-------|---------|-----------|
| Jan 15 | John Doe | Proj X  | 8.0   | $150.00 | $1,200.00 |
| Jan 16 | John Doe | Proj X  | 6.5   | $150.00 | $975.00   |
```

### Check Rate Card Usage

In the Rate Card Entry **list view**, new columns show:
- **Timesheets** - Number of entries
- **Hours Tracked** - Total hours
- **Billed Amount** - Total revenue

---

## Installation

### Prerequisites
- **hr_timesheet** module must be installed first

### Upgrade Steps

1. **Restart Odoo**
   ```bash
   sudo systemctl restart odoo
   ```

2. **Upgrade Module**
   - Apps → Search "Rate Card"
   - Click Upgrade (version 1.6.0)

3. **Verify**
   - Open Rate Card Entry
   - See "Timesheets" tab ✅

---

## Important Notes

### Timesheets Need to be Linked

This module **shows** timesheets but doesn't **link** them automatically.

**To link timesheets to rate cards:**
- You need integration code (separate module)
- When timesheet is validated, find matching rate card
- Set `tm_rate_card_entry_id` on timesheet
- See full documentation for code example

### If Stats Show Zero

This is normal if:
- No timesheets linked yet
- Need to implement linking logic
- Timesheets exist but not connected

---

## Fields Added

### On Rate Card Entry:
- `timesheet_ids` - Related timesheets
- `timesheet_count` - Number of timesheets
- `timesheet_hours` - Total hours
- `timesheet_amount` - Total billable amount

### On Timesheet (account.analytic.line):
- `tm_rate_card_entry_id` - Link to rate card
- `tm_billing_rate` - Billing rate used
- `tm_billable_amount` - Hours × Rate

---

## Quick Example: Linking a Timesheet

```python
# Find rate card for this timesheet
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
# tm_billable_amount auto-calculates
```

---

## Summary

- ✅ **View**: See timesheets from rate card
- ✅ **Track**: Monitor hours and billing
- ✅ **Analyze**: Stats and totals
- ⚠️ **Link**: Requires integration code

**Ready to upgrade!** 🚀

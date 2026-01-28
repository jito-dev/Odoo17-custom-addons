# Update Notes - Version 1.1.0

## Sales Order Integration Update

**Date:** 2026-01-27
**Version:** 1.0.0 → 1.1.0

---

## 🎉 What's New

### Sales Order Fields Added

Your rate cards can now be linked to **Sales Orders** and **Sales Order Lines** for enhanced traceability and contractual authorization.

**New Fields:**
1. **Sales Order** - Link to the SO that authorizes this rate
2. **Sales Order Line** - Link to specific SO line for this service

---

## ✨ Key Benefits

### 1. Contractual Traceability
Link rate cards directly to confirmed sales orders, providing clear audit trail that rates are authorized by signed contracts.

### 2. Contract-Specific Rates
Support different rates for the same employee/service based on which client contract (SO) the work is billed under.

**Example:**
- John Doe @ ACME Corp, Premium Contract (SO001): $200/hour
- John Doe @ ACME Corp, Standard Contract (SO002): $150/hour

### 3. Smart Auto-Fill
When you select a Sales Order Line, the system automatically fills:
- ✅ Sales Order
- ✅ Service Product
- ✅ Client (if not already set)
- ✅ Currency

---

## 📋 How to Use

### Creating a Rate Card with Sales Order

**Step 1:** Open Rate Card form
```
Rate Cards → Configuration → Rate Card Entries → Create
```

**Step 2:** Fill in the basics
- Company
- Client

**Step 3:** Select Sales Order (optional)
- Choose a confirmed Sales Order for that client
- System will filter to show only orders for the selected client

**Step 4:** Select Sales Order Line (optional)
- Choose the SO line that represents the service
- **Service Product, Client, Currency auto-fill!** 🎉

**Step 5:** Complete the rate card
- Employee
- Rate
- Dates

### Example Workflow

```
1. Client: ACME Corp
2. Sales Order: SO001 (Premium Support Contract - $100,000)
3. Sales Order Line: Line 2 - Premium Dev Hours (Product: Dev Hour, Qty: 500)
   → Service Product auto-fills: "Dev Hour"
   → Currency auto-fills: USD
4. Employee: John Doe
5. Rate: $200.00
6. Valid From: 2026-01-01
7. Save
```

---

## 🔄 Backward Compatibility

**Good news:** This update is **100% backward compatible**!

- ✅ Existing rate cards continue to work without changes
- ✅ Sales Order fields are **optional**
- ✅ No data migration required
- ✅ Old workflows still work exactly the same

You can:
- Keep creating rate cards without SO links (works as before)
- Start using SO links on new rate cards
- Mix both approaches

---

## 🔧 What Changed Technically

### Model Changes
- Added `sale_order_id` field (Many2one to sale.order)
- Added `sale_order_line_id` field (Many2one to sale.order.line)
- Updated unique combination to include SO line
- Added onchange methods for auto-fill behavior
- Updated immutability rules (SO fields are pricing-critical)

### View Changes
- **Tree View:** Added SO and SO Line columns (optional, visible)
- **Form View:** Added SO fields in Dimensions section
- **Search View:** Added filters "Linked to SO" and "Not Linked to SO"
- **Search View:** Added group by "Sales Order"

### Dependencies
- Added `sale` module dependency (standard Odoo module)

---

## 📦 Upgrade Instructions

### For Existing Installations

1. **Update module files** (already done if you pulled latest code)

2. **Upgrade module in Odoo:**
   ```bash
   # Method 1: Via UI
   Settings → Apps → Search "Rate Card" → Click "Upgrade" button

   # Method 2: Via command line
   odoo-bin -d your_database -u tm_rate_card --stop-after-init
   ```

3. **Clear browser cache:**
   - Windows/Linux: `Ctrl + F5`
   - Mac: `Cmd + Shift + R`

4. **Verify upgrade:**
   - Open a rate card form
   - You should see "Sales Order" and "Sales Order Line" fields
   - Try creating a new rate card with SO link

**Upgrade time:** ~30 seconds (no data migration needed)

---

## 🧪 Quick Test

**Test the new functionality:**

1. Go to: `Rate Cards → Configuration → Rate Card Entries → Create`
2. Select a **Client** that has confirmed Sales Orders
3. Select a **Sales Order** (dropdown will show only that client's confirmed orders)
4. Select a **Sales Order Line**
5. Watch the magic ✨:
   - Service Product auto-fills from SO line
   - Currency auto-fills from SO
6. Complete the form (Employee, Rate, Dates) and Save

**Expected result:** Rate card created successfully with SO link visible in the name display.

---

## 📊 Use Cases

### Use Case 1: Finance Audit
**Scenario:** Finance needs to verify that billed rates are authorized

**Solution:** Rate cards now show which SO authorized the rate
- Filter by "Linked to Sales Order"
- Group by Sales Order
- See clear link: Rate → SO → Contract

### Use Case 2: Multiple Contracts per Client
**Scenario:** Same employee, same client, different rates for different contracts

**Solution:** Create separate rate cards per SO line
- Rate Card A: ACME / SO001 / Premium Dev / John → $200/hr
- Rate Card B: ACME / SO002 / Standard Dev / John → $150/hr
- System allows both (different SO lines = different unique combo)

### Use Case 3: Project Tracking
**Scenario:** Track which projects are billed under which contract

**Solution:** Combine Project + SO fields
- Rate Card: ACME / Project Alpha / SO001 / Dev Hour / John → $175/hr
- Clear visibility: Project Alpha work is billed under SO001

---

## 🐛 Known Issues

None reported. This is a stable release.

---

## ❓ FAQ

**Q: Do I have to use Sales Orders now?**
A: No! SO fields are optional. You can continue creating rate cards without SO links.

**Q: What happens to my existing rate cards?**
A: Nothing changes. They continue to work exactly as before. SO fields will be blank (which is valid).

**Q: Can I edit the SO link after locking a rate card?**
A: No. Once locked, SO fields become immutable (like other pricing fields) to maintain integrity.

**Q: What if I select the wrong SO line?**
A: Just change it before saving. After saving, if the rate card is draft, you can edit. If locked, you cannot.

**Q: Does this affect the rate resolution service?**
A: No. The resolution service still works the same way. SO fields are for traceability, not resolution logic.

**Q: Can I have the same employee/service for different SO lines?**
A: Yes! SO line is part of the unique combination, so different SO lines = different rate cards allowed.

---

## 📞 Support

For issues or questions:
1. Check **CHANGELOG.md** for detailed technical changes
2. Check **README.md** for updated usage guide
3. Check **GUIDANCE.md** for developer reference
4. Contact your system administrator

---

## 🎓 Next Steps

1. **Upgrade the module** (see instructions above)
2. **Review your existing rate cards** - consider adding SO links for traceability
3. **Train your team** on the new SO linking workflow
4. **Enjoy better audit trails** 🎉

---

**Happy Rate Card Managing!** 🚀

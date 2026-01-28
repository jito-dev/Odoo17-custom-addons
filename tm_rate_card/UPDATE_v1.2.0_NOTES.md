# Update Notes - Version 1.2.0

## Fully Optional Date Ranges

**Date:** 2026-01-27
**Version:** 1.1.0 → 1.2.0

---

## 🎉 What's New

### Both Dates Are Now Optional!

You can now create rate cards with **any combination** of date ranges:

| Valid From | Valid Until | Meaning | Display |
|------------|-------------|---------|---------|
| ✅ Set | ✅ Set | Valid between two dates | `2026-01-01 → 2026-12-31` |
| ✅ Set | ❌ Blank | Valid from date onwards | `2026-01-01 → ∞` |
| ❌ Blank | ✅ Set | Valid until date | `∞ → 2026-12-31` |
| ❌ Blank | ❌ Blank | Valid for all time | `∞ ↔ ∞ (all time)` |

---

## ✨ Key Benefits

### 1. Default/Perpetual Rates
Create rates that are valid forever (no date restrictions at all).

**Example:**
```
Default Rate for ACME Corp:
- Valid From: (blank)
- Valid Until: (blank)
- Rate: $150/hour
→ This rate applies for ANY date if no more specific rate exists
```

### 2. Legacy Rates (Valid Until)
Define rates that were valid from "the beginning" until a specific date.

**Example:**
```
Old Rate:
- Valid From: (blank)
- Valid Until: 2025-12-31
- Rate: $100/hour
→ This was the historical rate until we changed it

New Rate:
- Valid From: 2026-01-01
- Valid Until: (blank)
- Rate: $125/hour
→ Clean transition without gaps
```

### 3. Maximum Flexibility
Support any rate management scenario without workarounds.

---

## 📋 How to Use

### Creating an "All Time" Rate Card

**Step 1:** Create rate card as usual
```
Rate Cards → Configuration → Rate Card Entries → Create
```

**Step 2:** Fill in the basics
- Company
- Client
- Service Product
- Employee
- Rate

**Step 3:** Leave BOTH date fields blank!
- Valid From: (leave empty)
- Valid Until: (leave empty)

**Step 4:** Save

**Result:** Rate card is valid for all time! Display will show: `∞ ↔ ∞ (all time)`

---

## 🔄 Backward Compatibility

**100% backward compatible!**

- ✅ Existing rate cards work unchanged
- ✅ Old workflows still work
- ✅ No data migration required
- ✅ This is additive functionality only

---

## 🔧 What Changed Technically

### Field Changes
- `date_start` is now **optional** (was required before)
- Both dates can be NULL/blank

### Logic Updates
- **Overlap constraint** handles all four date combinations
- **Resolution service** matches rates with NULL dates correctly
- **Display names** show intuitive labels (∞ symbols)

### UI Updates
- **Form view:** Updated help text explaining all options
- **No required indicator** on Valid From field
- Same tree/search views (no visual changes)

---

## 📦 Upgrade Instructions

### For Existing Installations

1. **Update module files** (already done if you pulled latest code)

2. **Upgrade module in Odoo:**
   ```bash
   # Method 1: Via UI
   Settings → Apps → Search "Rate Card" → Upgrade

   # Method 2: Via command line
   odoo-bin -d your_database -u tm_rate_card --stop-after-init
   ```

3. **Clear browser cache:**
   - Windows/Linux: `Ctrl + F5`
   - Mac: `Cmd + Shift + R`

4. **Verify upgrade:**
   - Open a rate card form
   - "Valid From" should NOT have a red asterisk (not required)
   - Try creating a rate card with no dates

**Upgrade time:** ~30 seconds

---

## 🧪 Quick Test

**Test the new functionality:**

1. Go to: `Rate Cards → Configuration → Rate Card Entries → Create`
2. Fill in: Client, Service Product, Employee, Rate
3. **Leave both date fields blank**
4. Save
5. Check the display name → should show `∞ ↔ ∞ (all time)`
6. Try to create another with same combo but no dates → should FAIL (overlap!)

**Expected result:** You can create "all time" rate cards, and the system correctly prevents overlaps.

---

## 📊 Common Use Cases

### Use Case 1: Default Rate
**Scenario:** You want a default rate that applies when no other rate card matches

**Solution:**
```
Create rate card with:
- Valid From: (blank)
- Valid Until: (blank)
→ This becomes your fallback/default rate
```

### Use Case 2: Phase-Out Old Rates
**Scenario:** You're migrating from old system and need to represent historical rates

**Solution:**
```
Historical Rate:
- Valid From: (blank)
- Valid Until: 2025-12-31
- Rate: $100/hour

Current Rate:
- Valid From: 2026-01-01
- Valid Until: (blank)
- Rate: $125/hour

No gap, clean transition!
```

### Use Case 3: Future Rate Increase
**Scenario:** Employee gets raise starting June 2026

**Solution:**
```
Current Rate:
- Valid From: (blank)
- Valid Until: 2026-05-31
- Rate: $150/hour

Future Rate:
- Valid From: 2026-06-01
- Valid Until: (blank)
- Rate: $175/hour

Or just create the future rate with Set+Blank dates!
```

---

## 🔍 How Overlap Detection Works

The system prevents overlaps for all combinations:

**Example 1: All Time vs. Any Other**
```
Rate A: (blank) to (blank) = ∞ ↔ ∞
Rate B: 2026-01-01 to 2026-12-31
→ OVERLAP! (All time includes 2026)
```

**Example 2: Indefinite Past vs. Set Future**
```
Rate A: (blank) to 2025-12-31 = ∞ → 2025-12-31
Rate B: 2026-01-01 to (blank) = 2026-01-01 → ∞
→ NO OVERLAP (dates don't touch)
```

**Example 3: Indefinite Future vs. Set Past**
```
Rate A: 2026-01-01 to (blank) = 2026-01-01 → ∞
Rate B: (blank) to 2025-12-31 = ∞ → 2025-12-31
→ NO OVERLAP (dates don't touch)
```

**Example 4: Two Indefinite Futures**
```
Rate A: 2026-01-01 to (blank) = 2026-01-01 → ∞
Rate B: 2026-06-01 to (blank) = 2026-06-01 → ∞
→ OVERLAP! (Both cover June onwards)
```

---

## 🐛 Known Issues

None reported. This is a stable release.

---

## ❓ FAQ

**Q: Can I leave Valid From blank?**
A: Yes! The rate will be valid from the beginning of time until Valid Until (or forever if that's also blank).

**Q: What happens to my existing rate cards?**
A: Nothing changes. They all have Valid From set, so they work exactly as before.

**Q: Can I have multiple "all time" rates for the same combo?**
A: No. The overlap constraint will prevent this (they would overlap for all dates).

**Q: How does resolution service handle NULL dates?**
A: NULL date_start means "valid from -∞" and NULL date_end means "valid until +∞". The query matches correctly.

**Q: Can I edit dates to make them blank after creation?**
A: Yes, if the rate card is in draft state. Once locked, date fields are immutable.

**Q: What's the use case for blank Valid From?**
A: Legacy rates from previous systems, default/fallback rates, or "valid until superseded" scenarios.

---

## 📞 Support

For issues or questions:
1. Check **CHANGELOG.md** for detailed technical changes
2. Check **README.md** for full usage guide
3. Contact your system administrator

---

## 🎓 Next Steps

1. **Upgrade the module** (see instructions above)
2. **Test the new functionality** with a blank-date rate card
3. **Consider migrating** old default rates to use blank dates for clarity
4. **Enjoy the flexibility!** 🎉

---

**Happy Rate Card Managing!** 🚀

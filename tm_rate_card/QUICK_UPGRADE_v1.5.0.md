# Quick Upgrade Guide - Rate Card v1.5.0

## What's New
✅ **Client now auto-fills from Sales Order** (no manual selection)
✅ Sales Order is now the first field to select
✅ Simpler, faster workflow

---

## New Workflow

**Old way (v1.4.0):**
1. Select Client ❌
2. Select Sales Order
3. Select Sales Order Line
4. Service Product auto-fills

**New way (v1.5.0):**
1. **Select Sales Order** ← First!
2. **Client auto-fills** ← Automatic!
3. Select Sales Order Line
4. Service Product auto-fills

---

## Before Upgrading - IMPORTANT!

### Check if you have entries without Sales Order:

Go to **Rate Cards → Rate Card Entries**

If you see entries where **Sales Order** is empty:
- ⚠️ These will cause problems after upgrade
- **Fix:** Edit them and add a Sales Order
- **Or:** Delete them if they're not needed

---

## Upgrade Steps

### 1. Restart Odoo
```bash
sudo systemctl restart odoo
```

### 2. Upgrade Module
1. Open Odoo
2. Go to **Apps**
3. Remove "Apps" filter
4. Search: **Rate Card**
5. Version should show **1.5.0**
6. Click **Upgrade**

### 3. Test
1. Create new rate card entry
2. Select **Sales Order first**
3. See **Client auto-fill** ✅
4. Client field is **gray/readonly** ✅

---

## Troubleshooting

**Q: Client field is empty?**
- A: The Sales Order you selected has no customer. Fix the Sales Order first.

**Q: Can't change client?**
- A: Correct! Client is now readonly. Change the Sales Order instead.

**Q: "Sales Order is required" error?**
- A: Sales Order is now mandatory. You must select one.

---

## Summary

- **Client = Auto from Sales Order** ✅
- **Sales Order = Required** ✅
- **Workflow = Simpler** ✅

Done! 🎉

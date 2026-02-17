# Testing Checklist: Timesheet Export Feature (v1.10.0)

## Overview
This document provides a comprehensive testing plan for the newly implemented timesheet export feature in the `tm_billing_control` module.

---

## Prerequisites

### 1. Module Upgrade
```bash
# From Odoo root directory
python3 odoo17_community/odoo-bin -c <your_config>.conf -u tm_billing_control --stop-after-init
```

### 2. Test Data Requirements
- At least one billing run in **preview**, **invoiced**, or **closed** state
- Billing run should have:
  - Multiple projects (for grouping testing)
  - Multiple employees (for grouping testing)
  - At least 50+ timesheets (to test preview limit)
  - Mix of included and excluded timesheets (optional)

---

## Test Scenarios

### ✅ Test 1: Access Control
**Objective:** Verify security permissions

**Steps:**
1. Login as **Billing Control Viewer** user
2. Navigate to a billing run in preview state
3. Click "Export Timesheets" button
4. Verify wizard opens
5. Verify viewer can only read (no create/write/delete on wizard)

**Expected Results:**
- Viewer can access export wizard (read-only)
- Manager can access export wizard (full access)

---

### ✅ Test 2: State Restrictions
**Objective:** Verify export is only available in correct states

**Steps:**
1. Create new billing run (state: **draft**)
2. Verify "Export Timesheets" button is **not visible**
3. Click "Compute Preview" (state: **preview**)
4. Verify "Export Timesheets" button **is visible**
5. Create invoice (state: **invoiced**)
6. Verify "Export Timesheets" button **is visible**
7. Close billing run (state: **closed**)
8. Verify "Export Timesheets" button **is visible**

**Expected Results:**
- Export button only visible in preview, invoiced, closed states
- Export button hidden in draft state

---

### ✅ Test 3: Wizard - Step 1 (Choose Formats)
**Objective:** Test format selection

**Steps:**
1. Open billing run in preview state
2. Click "Export Timesheets"
3. Verify wizard opens in "Choose Formats" state
4. Verify billing run summary displays:
   - Client name
   - Period (start to end dates)
   - Total hours
   - Total amount with currency
5. Verify checkboxes for Excel and CSV formats
6. Verify Excel is checked by default
7. **Test validation:** Uncheck both formats, click "Preview Export Data"
8. Verify error: "Please select at least one export format"

**Expected Results:**
- Summary information displays correctly
- Excel checked by default, CSV unchecked
- Validation error when no format selected

---

### ✅ Test 4: Wizard - Step 2 (Preview Data)
**Objective:** Test data preview

**Steps:**
1. From Step 1, select both Excel and CSV formats
2. Click "Preview Export Data"
3. Verify wizard transitions to "Preview Data" state
4. Verify preview shows:
   - Alert message: "Showing first X rows of Y total rows"
   - Table with columns: Project, Employee, Date, Task, Description, Hours, Rate, Amount, Included
   - First 50 rows (if more than 50 total)
5. Verify "Generate Export" button visible
6. Verify "Back" button visible
7. Click "Back" button
8. Verify wizard returns to Step 1

**Expected Results:**
- Preview displays first 50 rows
- Data matches billing run timesheets
- Navigation works correctly

---

### ✅ Test 5: Wizard - Step 3 (Download Files)
**Objective:** Test file generation and download

**Steps:**
1. From Step 2 preview, click "Generate Export"
2. Verify wizard transitions to "Download Files" state
3. Verify success message displays
4. Verify attachment list shows generated files:
   - File names match pattern: `Billing_Run_{reference}_{client}_{date}.xlsx/csv`
   - Mimetypes correct (xlsx: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet, csv: text/csv)
   - File sizes populated
   - Create dates populated
5. Verify "Download" button on each attachment
6. Click "Close" to exit wizard

**Expected Results:**
- Files generated successfully
- File names follow naming convention
- Files linked as attachments to billing run

---

### ✅ Test 6: Excel Export Content
**Objective:** Verify Excel file structure and content

**Steps:**
1. Generate Excel export
2. Download and open file in Microsoft Excel / LibreOffice Calc
3. Verify worksheet name: "Timesheets"
4. Verify header row (row 1) with formatting:
   - Bold, gray background, centered
   - 18 columns: Billing Run Ref, Period Start, Period End, Client, Project, Employee, Date, Task, Description, Hours, Rate, Amount, Currency, Product/Service, Sales Order, Included, Invoice Number, Invoice State
5. Verify column widths are readable
6. Verify data rows:
   - Sorted by Project → Employee → Date
   - Date columns formatted as YYYY-MM-DD
   - Number columns formatted with 2 decimals
7. Verify grouping and subtotals:
   - Employee subtotals (within each project)
   - Project totals
   - Grand total at bottom (bold, with border)
8. Verify frozen header row (scroll down, header stays visible)

**Expected Results:**
- Professional formatting applied
- Data grouped logically
- Subtotals and grand total correct
- All data matches billing run

---

### ✅ Test 7: CSV Export Content
**Objective:** Verify CSV file structure and content

**Steps:**
1. Generate CSV export
2. Download and open file in Excel / Text editor
3. Verify header row with same 18 columns as Excel
4. Verify data rows (no formatting, plain text)
5. Verify no subtotals/grand totals (flat data)
6. Verify special characters handled correctly (commas in descriptions quoted)
7. Import CSV into Excel and verify readability

**Expected Results:**
- Plain text format
- All data present and correct
- Importable into spreadsheet applications

---

### ✅ Test 8: Export from Different States
**Objective:** Verify exports work correctly in all allowed states

**Steps:**
1. **Preview State:**
   - Export from billing run in preview state
   - Verify "Invoice Number" and "Invoice State" columns are empty
2. **Invoiced State:**
   - Export from billing run in invoiced state
   - Verify "Invoice Number" populated (e.g., INV/2026/0042)
   - Verify "Invoice State" populated (e.g., Posted, Draft)
3. **Closed State:**
   - Export from billing run in closed state
   - Verify invoice information populated

**Expected Results:**
- Exports work in all three states
- Invoice columns empty in preview state
- Invoice columns populated in invoiced/closed states

---

### ✅ Test 9: Export with Excluded Timesheets
**Objective:** Verify included/excluded status shown correctly

**Steps:**
1. Open billing run in preview state
2. Open a billing line, click "Manage Timesheets"
3. Exclude some timesheets (toggle "Included" to off)
4. Save and close
5. Export timesheets
6. Open Excel file
7. Verify "Included" column shows:
   - "Yes" for included timesheets
   - "No" for excluded timesheets
8. Verify excluded timesheets still appear in export

**Expected Results:**
- Excluded timesheets shown with "Included = No"
- All timesheets present (included and excluded)
- Totals in billing run reflect only included timesheets

---

### ✅ Test 10: Export with Grouping Options
**Objective:** Test exports with different grouping settings

**Steps:**
1. **Test with group_by_project = True:**
   - Create billing run with "Group by Project" enabled
   - Compute preview
   - Export timesheets
   - Verify Excel has clear project sections with subtotals
2. **Test with group_by_month = True:**
   - Create billing run spanning 2+ months with "Group by Month" enabled
   - Compute preview
   - Export timesheets
   - Verify "Period Month" column populated (e.g., "2026-01")

**Expected Results:**
- Project grouping creates logical sections
- Month grouping shown in data

---

### ✅ Test 11: Large Export Performance
**Objective:** Test performance with large datasets

**Steps:**
1. Create billing run with 1000+ timesheets
2. Compute preview
3. Export to Excel
4. Measure time taken
5. Verify export completes successfully
6. Open Excel file and verify all data present

**Expected Results:**
- Export completes in under 30 seconds for 1000 timesheets
- File opens correctly without corruption
- All rows present (check row count)

---

### ✅ Test 12: Multi-Company Access
**Objective:** Verify multi-company record rules

**Steps:**
1. Create billing run in Company A
2. Login as user from Company B (without access to Company A)
3. Navigate to Billing Runs
4. Verify billing run from Company A is **not visible**
5. Login as user with access to both companies
6. Verify can export from both companies' billing runs

**Expected Results:**
- Record rules enforce company access
- Export inherits parent billing run's company

---

### ✅ Test 13: Attachment Audit Trail
**Objective:** Verify attachments linked to billing run

**Steps:**
1. Export timesheets (generate both Excel and CSV)
2. Close wizard
3. Go to Billing Run form view
4. Open "Attachments" (paperclip icon in header)
5. Verify both export files listed as attachments
6. Verify files downloadable from attachments list
7. Delete one attachment
8. Re-export
9. Verify new attachment created

**Expected Results:**
- Attachments linked to billing run record
- Attachments persist after wizard closes
- Attachments accessible from billing run form

---

### ✅ Test 14: Edge Cases
**Objective:** Test edge case scenarios

**Steps:**
1. **Empty Billing Run:**
   - Create billing run with no billing lines
   - Try to export
   - Verify error: "No billing lines to export"
2. **Billing Run with No Timesheets:**
   - (Should not be possible, but test via code if needed)
3. **Special Characters in Data:**
   - Create timesheet with description containing: quotes, commas, newlines
   - Export to CSV
   - Verify special characters handled correctly (quoted/escaped)
4. **Long Client Names:**
   - Test with client name containing spaces and special characters
   - Verify filename sanitized correctly (underscores replace spaces)

**Expected Results:**
- Appropriate error messages for edge cases
- Special characters handled gracefully
- File names sanitized correctly

---

### ✅ Test 15: Concurrent Exports
**Objective:** Test multiple users exporting simultaneously

**Steps:**
1. Login as two different users (User A and User B)
2. Both users open same billing run
3. Both users click "Export Timesheets" at same time
4. Both users generate exports
5. Verify both exports complete successfully
6. Verify each user gets their own attachments

**Expected Results:**
- No conflicts or locking issues
- Each user's export completes independently

---

## Regression Testing

### ✅ Test 16: Existing Functionality Not Affected
**Objective:** Ensure export feature doesn't break existing features

**Steps:**
1. Test full billing run workflow:
   - Create billing run (draft)
   - Compute preview
   - Manage timesheets (include/exclude)
   - Create invoice
   - Confirm invoice
   - Close billing run
2. Verify all existing buttons and features work
3. Verify computed fields (hours, amounts, counts) update correctly
4. Verify security and access controls unchanged

**Expected Results:**
- All existing features work as before
- No regressions introduced

---

## Manual Test Execution Log

| Test # | Test Name | Date | Tester | Result | Notes |
|--------|-----------|------|--------|--------|-------|
| 1 | Access Control | | | ☐ Pass / ☐ Fail | |
| 2 | State Restrictions | | | ☐ Pass / ☐ Fail | |
| 3 | Wizard Step 1 | | | ☐ Pass / ☐ Fail | |
| 4 | Wizard Step 2 | | | ☐ Pass / ☐ Fail | |
| 5 | Wizard Step 3 | | | ☐ Pass / ☐ Fail | |
| 6 | Excel Content | | | ☐ Pass / ☐ Fail | |
| 7 | CSV Content | | | ☐ Pass / ☐ Fail | |
| 8 | Different States | | | ☐ Pass / ☐ Fail | |
| 9 | Excluded Timesheets | | | ☐ Pass / ☐ Fail | |
| 10 | Grouping Options | | | ☐ Pass / ☐ Fail | |
| 11 | Large Export | | | ☐ Pass / ☐ Fail | |
| 12 | Multi-Company | | | ☐ Pass / ☐ Fail | |
| 13 | Attachment Audit | | | ☐ Pass / ☐ Fail | |
| 14 | Edge Cases | | | ☐ Pass / ☐ Fail | |
| 15 | Concurrent Exports | | | ☐ Pass / ☐ Fail | |
| 16 | Regression | | | ☐ Pass / ☐ Fail | |

---

## Known Issues / Limitations

### Current Limitations:
1. Export preview limited to first 50 rows (by design)
2. Excel row limit is 1,048,576 rows (Odoo limitation unlikely to reach this)
3. Large exports (5000+ timesheets) may take 30+ seconds
4. No option to customize column selection (future enhancement)

### Future Enhancements (Not in Scope):
- Summary export (billing line level, not timesheet level)
- Custom column selection
- PDF export
- Scheduled/automated exports
- Email delivery of exports
- Advanced filtering (export specific projects/employees only)

---

## Acceptance Criteria

✅ **Feature Complete When:**
1. All 16 test scenarios pass
2. No critical or major bugs found
3. Performance acceptable (< 30s for 1000 timesheets)
4. Security and access controls working correctly
5. Documentation updated (CLAUDE.md)
6. User training materials prepared (if needed)

---

**Testing Status:** ⏳ Pending
**Last Updated:** 2026-02-09
**Module Version:** 1.10.0

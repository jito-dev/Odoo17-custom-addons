# hr_payroll_for_contractors — Module Guidance

**Version:** 1.2.3
**Author:** JITO LTD
**Depends:** hr, project, hr_timesheet, timesheet_grid, account, mail

---

## Overview

This module manages contractor payroll using timesheets (`account.analytic.line`). Both validated and non-validated timesheets are included. Three contracting types are supported. The UI follows the Billing Control module layout: separate menu items for Dashboard, Salary Runs, Contracts, and Configuration.

---

## Contracting Types

| Type | Key | Compensation Logic |
|------|-----|--------------------|
| Hourly | `hourly` | `regular_hours × rate` (excludes sickness/vacation/holiday hours) |
| Monthly Tracking | `monthly_tracking` | `(tracked_hours / expected_hours) × monthly_compensation` (capped at 1.0 unless overtime) |
| Monthly Fixed | `monthly_fixed` | Always `monthly_compensation` |

---

## Main Models

### `hr.payroll.contractor.settings` (Singleton)
- One record per company; created by `post_init_hook` on install.
- Accessed via server action `action_hpc_open_main()` (dashboard view).
- Holds configuration, period navigation, and all One2many refs.
- Methods:
  - `action_refresh_dashboard`, `action_previous/this/next_month` — dashboard navigation
  - `action_create_batch_salary_runs` — opens batch wizard
  - `action_open_contracts()` — opens standalone contracts list (filters by settings_id)
  - `action_open_config()` — opens config-only form view of the singleton

### `hr.payroll.contractor.contract`
- Links an employee to a contracting type and rate.
- Constraint: no overlapping date ranges per employee (`_check_no_overlap`).
- `settings_id` FK links it to the singleton (required, set via context on create).

### `hr.payroll.contractor.salary.run`
- Inherits `mail.thread`, `mail.activity.mixin`.
- States: `draft → approved_and_locked → invoiced`.
- Sequence: `PCRUN/0001`.
- `action_compute()` fetches all timesheets (validated and non-validated) and creates `salary.ts` lines.
- `action_approve()` transitions `draft → approved_and_locked`.
- `action_unlock()` reverts `approved_and_locked → draft` (blocked if invoice exists).
- `action_create_invoice()` creates an `account.move (in_invoice)` against the employee's work contact.
- `action_open_bill()` — UI navigation helper to open the linked vendor bill.
- `_check_monthly_period` constraint: monthly contracts must use full-month periods (1st to last day).
- SQL unique constraint on `(settings_id, employee_id, date_start, date_end, contract_id)`.

### `account.move` (inherited)
- `unlink()` override: when a vendor bill linked to a salary run is deleted, the run state reverts to `approved_and_locked` automatically.

### `hr.payroll.contractor.salary.ts`
- Junction: salary run ↔ `account.analytic.line`.
- `include` boolean (default True) controls which lines count in compensation.

### `hr.payroll.contractor.salary.adj`
- Free-form adjustment lines (positive or negative) on a salary run.
- Can have an attachment.

### `hr.payroll.contractor.dashboard.line` (TransientModel)
- Deleted and recreated each time dashboard is refreshed.
- Stores hourly breakdown per employee/contract for the selected period.

### `hr.payroll.contractor.batch.wizard` + `.line` (TransientModel)
- Preview wizard for creating multiple salary runs at once.
- Lines are built in `create()` override via `_build_preview_lines()`.

---

## Architecture: Menu & Navigation

Follows the same pattern as `tm_billing_control`:

```
Payroll for Contractors (app root → Dashboard)
├── Dashboard       → Settings singleton (dashboard form view)
├── Salary Runs     → Standalone salary runs list/kanban/form
├── Contracts       → Standalone contracts list/form (filtered to company settings)
└── Configuration   → Settings singleton (config form view, manager only)
```

Two separate form views of the same `hr.payroll.contractor.settings` model:
- `view_hpc_settings_dashboard_form` (priority=10): Dashboard layout with header navigation buttons, period title, employee overview table.
- `view_hpc_settings_config_form` (priority=16): Simple configuration with task sources.

---

## Views

| File | Contents |
|------|----------|
| `hpc_settings_views.xml` | Dashboard form + Config form + server actions for each section + dashboard line list/pivot |
| `hpc_contract_views.xml` | Contract tree + form + search view |
| `hpc_salary_run_views.xml` | Salary run form (with oe_button_box, oe_title, named groups, flat sections, calculation card) + tree + kanban + search + action |
| `hpc_batch_wizard_views.xml` | Batch creation popup |
| `hpc_employee_portal_views.xml` | Employee self-service: read-only contract tree+form+action, salary run tree+form+action, "My Payroll" app root + sub-menus |
| `hpc_menus.xml` | App root + 4 sub-menu items (Dashboard, Salary Runs, Contracts, Configuration) |

---

## Salary Run Form Layout (v1.1.8)

1. **Header**: action buttons (Compute Timesheets, Approve [highlighted in draft], Unlock [approved, no bill], Create Vendor Bill [approved, no bill], Open Vendor Bill [invoiced]) + statusbar
2. **oe_button_box**: Two conditional smart buttons — "Vendor Bill" (opens bill when exists) + "No Bill Yet" (creates bill when approved without bill)
3. **oe_title**: Reference as h1
4. **Named groups**: "Contract Information" (contract, employee, type, rate/compensation readonly) + "Period & Options"
5. **Vendor Bill group**: invoice_id (visible when invoice exists)
6. **Separator "Timesheets"** + flat `timesheet_line_ids` tree (readonly when locked/invoiced)
7. **Separator "Addings / Subtractions"** + flat `adjustment_ids` editable tree
8. **Payment Calculation card** (right-aligned, Bootstrap 5, hidden in draft):
   - Calculated Compensation row with inline hours
   - Monthly Tracking sub-row: expected hours, overtime hours, status badge (included / capped at 100% / no overtime)
   - Addings / Subtractions row
   - Divider + bold Total to Pay
9. **Chatter**: followers (group_user only), activities, messages

### Batch Wizard Navigation (v1.1.4)
- `action_create_single_run` returns `ir.actions.act_window` (closes wizard, opens the new salary run form).
- `action_create_all_selected` returns `display_notification` then `act_window_close` (bulk creation).

---

## Security

| Group | Access |
|-------|--------|
| `group_hpc_user` | Read-only on contracts/settings; CRUD on salary runs, ts, adj, wizards |
| `group_hpc_manager` | Full CRUD on all models; implies user group; Configuration menu item |
| `group_hpc_employee` | Read-only on own contracts and salary runs only (scoped by record rules); independent of user/manager groups |

### Employee Self-Service Portal (`group_hpc_employee`)

Contractors who are internal Odoo users can be given the `Payroll Contractor Employee` group. This grants:
- A dedicated **"My Payroll"** app menu (sequence=91), separate from the full "Payroll for Contractors" app
- **"My Salary Runs"** and **"My Contracts"** sub-menus — read-only, no create/edit/delete
- **Record rules** that restrict visibility to records where `employee_id.user_id = user.id`
  - `rule_hpc_contract_employee` on `hr.payroll.contractor.contract`
  - `rule_hpc_salary_run_employee` on `hr.payroll.contractor.salary.run`
- `salary.ts` and `salary.adj` lines only need ACL (no record rule) — they are always loaded through the parent salary run, which is already scoped

**Important**: The employee's `hr.employee` record must have the "Related User" (`user_id`) field set for record rules to work. This is standard Odoo practice.

---

## Important Patterns & Constraints

1. **Singleton**: `action_open_main()` does `search([('company_id','=',...)], limit=1)` and creates if not found. Dashboard lines auto-refresh on every open.
2. **Contracts require settings_id**: When opening contracts standalone, `context={'default_settings_id': record.id}` ensures new contracts link correctly.
3. **Timesheets**: All `account.analytic.line` records with a project are included (validated and non-validated).
4. **Vendor bill**: Created as `account.move(move_type='in_invoice')` with `partner_id=employee.work_contact_id`.
5. **Approved run**: Core fields (`contract_id`, `date_start`, `date_end`) cannot be changed; `action_unlock()` returns it to draft (disallowed if invoice exists). Timesheets and adjustments become read-only once approved.
6. **Bill deletion**: Inheriting `account.move.unlink()` detects linked salary runs and reverts their state to `approved_and_locked` automatically.
7. **Monthly period constraint**: For `monthly_tracking` and `monthly_fixed` contracts, `date_start` must be the 1st of the month and `date_end` must be the last day of that month (validated in draft state only).
8. **`include_overtime` override**: Initialized from `contract_id.include_overtime` on record create (via `create()`) and on contract change in UI (via `@api.onchange`). `action_compute()` never resets it — the salary run's value is always the user's override.
9. **Working days**: Monday–Friday count, no public holiday exclusion at this level (holidays are tracked via task source).
10. **Dashboard**: TransientModel lines; refreshed by delete + recreate pattern.
11. **Migration**: `post_migrate_hook` in `hooks.py` migrates existing `locked` records to `approved_and_locked` on module upgrade.

---

## Verification Checklist

- Install module without errors
- "Payroll for Contractors" app appears in app list (opens Dashboard)
- Dashboard sub-menu: period navigation in header works, employee table populates
- Salary Runs sub-menu: tree/kanban/form views load, create salary run works
- Contracts sub-menu: standalone contracts list loads, create contract sets settings_id
- Configuration sub-menu: config form loads (manager only), task fields work
- Salary run form: smart button shows vendor bill, calculation card visible after compute
- Batch wizard: preview lines computed, create selected runs
- Verify vendor bill created against employee work contact

### Employee Self-Service Checklist (v1.2.3)

1. As admin: assign `Payroll Contractor Employee` group to an internal user linked to an employee (`hr.employee.user_id` set)
2. Log in as that user: "My Payroll" app appears; full "Payroll for Contractors" does NOT appear (unless also in `group_hpc_user`)
3. "My Salary Runs": only that employee's runs shown; form is fully read-only (no action buttons in header)
4. "My Contracts": only that employee's contracts shown; form is fully read-only
5. As a different employee user: confirm they see only their own records
6. As manager (`group_hpc_manager`): confirm full "Payroll for Contractors" app is unaffected

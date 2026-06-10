# hr_payroll_for_contractors — Module Guidance

**Version:** 1.5.10
**Author:** JITO LTD
**Depends:** hr, project, hr_timesheet, timesheet_grid, account, mail, jito_document_template, sign

---

## Overview

This module is a merged all-in-one payroll solution for contractors. It combines the former `hr_payroll_for_contractors` (core engine), `hpc_contractor_info` (contractor identity), `hr_payroll_ua_pe` (Ukrainian PE fields), and `hpc_revolut_payments` (Revolut CSV export) into a single installable module.

It manages contractor payroll using timesheets (`account.analytic.line`). Both validated and non-validated timesheets are included. Three contracting types are supported. The UI follows the Billing Control module layout: separate menu items for Dashboard, Salary Runs, Contracts, and Configuration.

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
  - ~~`action_employee_open_main()`~~ — **removed in v1.4.0** (My Payroll root menu now points directly to `action_hpc_employee_salary_runs`)

### `hr.payroll.contractor.contract`
- Links an employee to a contracting type and rate.
- Constraint: no overlapping date ranges per employee (`_check_no_overlap`).
- `settings_id` FK links it to the singleton (required, set via context on create).

### `hr.payroll.contractor.salary.run`
- Inherits `mail.thread`, `mail.activity.mixin`.
- States: `draft → approved_and_locked → invoiced`.
- Sequence: `PCRUN/0001`.
- `action_compute()` fetches all timesheets (validated and non-validated), creates `salary.ts` lines, and resets `employee_confirmation → 'waiting'`.
- `action_approve()` transitions `draft → approved_and_locked`.
- `action_unlock()` reverts `approved_and_locked → draft` (blocked if invoice exists); resets `employee_confirmation → 'waiting'`.
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
| `hpc_employee_portal_views.xml` | Employee self-service: read-only contract tree+form+action, salary run tree+form+action, settings singleton employee form (My Payroll landing with "My Salary Runs" tab), server action, "My Payroll" app root (with action) + sub-menus |
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

Four groups under Human Resources / Payroll:

| XML ID | Display Name | Access |
|--------|-------------|--------|
| `group_hpc_user` | Payroll Contractor Manager | Full CRUD on contracts, salary runs, ts, adj, wizards. Cannot access Configuration settings. |
| `group_hpc_manager` | Payroll Administrator | All Payroll Contractor Manager rights + Configuration settings. Implies `group_hpc_user`. |
| `group_hpc_ts_reviewer` | Payroll Timesheets Reviewer | Read-only on all models; financial data (rates, totals, bills) hidden in views. |
| `group_hpc_employee` | Payroll Contractor Employee | Sees/edits own salary runs and contracts only (record rules). Can add/edit/delete adjustments and confirm compensation. |

**Note**: XML IDs (`group_hpc_user`, `group_hpc_manager`, etc.) are unchanged from v1.3.0 — only display names changed — so existing DB group assignments are preserved.

### Employee Self-Service Portal (`group_hpc_employee`)

Contractors who are internal Odoo users can be given the `Payroll Contractor Employee` group. This grants:
- A dedicated **"My Payroll"** app menu (sequence=91), pointing directly to the salary runs list
- **"My Salary Runs"** and **"My Contracts"** sub-menus
- Salary run form: read-only except **adjustments are editable** (until `invoiced` state)
- **"Confirm Compensation"** button on `approved_and_locked` runs — sets `employee_confirmation = 'confirmed'`
- **Record rules** that restrict visibility to records where `employee_id.user_id = user.id`
  - `rule_hpc_contract_employee` on `hr.payroll.contractor.contract`
  - `rule_hpc_salary_run_employee` on `hr.payroll.contractor.salary.run` (read+write)
  - `rule_hpc_salary_adj_employee` on `hr.payroll.contractor.salary.adj` (full CRUD)
- Write protection in `salary.run.write()`: employees can only write `adjustment_ids` (all other fields blocked at ORM level)

**Important**: The employee's `hr.employee` record must have the "Related User" (`user_id`) field set for record rules to work.

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

## Additional Models (Contractor Identity)

### `hpc.contractor`
- One record per employee; aggregates all legal entities and payment methods.
- Unique constraint: one contractor per employee.

### `hpc.contractor.legal.entity`
- Supports `ua_pe`, `ca_sp`, and `individual` types.
- 70+ fields: personal info (UA/EN), address, identity documents (ID card / paper passport / international passport).
- **`ca_sp` Canadian Sole Proprietor (v1.5.9)**: `ca_sp_first_name` (req), `ca_sp_last_name` (req), `ca_sp_business_name`, `ca_sp_business_id_number`, `ca_sp_tax_id_number`, `ca_sp_principal_address` (Text, req), `ca_sp_federal_business_number`. Required modifiers are view-level (`required="entity_type == 'ca_sp'"`) so they only fire when the entity is Canadian SP. Identity Document section reuses the shared `intl_passport_*` fields; `ca_sp_id_doc_type` Selection currently has only `international_passport` (Selection kept for forward compatibility).

### `hpc.contractor.payment.method`
- Selection: SEPA, SWIFT, GBP, Ukrainian Bank Card, Cash, Crypto.
- Method-specific fields (IBAN, BIC, account numbers, etc.).

### `hpc.contract.extension` (inherits `hr.payroll.contractor.contract`)
- Adds `legal_entity_id`, `payment_method_id`, `service_agreement_id` (computed).
- Revolut fields computed from legal entity + payment method.

### `hpc.contract.service.agreement`
- Singleton instance per contract.
- DOCX/PDF document generation using `jito_document_template`.
- Odoo Sign integration for signing.
- Sequence: `CSA/0001`.
- **Create Vendor** button: creates `res.partner` (supplier_rank=1) from legal entity data (name EN, address EN, VAT, country) + employee email/phone. If payment method is SEPA/SWIFT/GBP, also creates `res.partner.bank` with account number and BIC. Stored in `vendor_id` field.
- **`is_templated` toggle (v1.5.8)**: default True. When off, the SA is "one-time": `template_id` and the **Agreement Terms** group hide, and the **Agreement / Termination / Context** notebook tabs hide. `template_id` is no longer `required=True` at the field level — instead a `@api.constrains` enforces it whenever `is_templated` is True. Templated-only actions (`action_generate_agreement`, `action_generate_termination`, `action_send_*_for_signing`, `action_rebuild_context`) call `_ensure_templated()` first and raise `UserError` if invoked on a one-time SA.
- **`signed_sign_request_ids` M2M (v1.5.8, broadened in v1.5.10)**: Many2many to `sign.request` (no state filter — any signing state can be attached, including in-progress `shared`/`sent`). Surfaced in the always-visible **Sign Documents** notebook tab. Used to attach Sign records (NDAs, addenda, or — for one-time SAs — the agreement itself). Independent of the existing `agreement_sign_template_id` / `termination_sign_template_id` auto-flow; both can coexist on the same record. Relation table: `hpc_contract_sa_signed_sign_request_rel`. Field name retains the `signed_` prefix for backwards compatibility with the v1.5.8 schema.

### `hpc.service.agreement`
- Singleton template per category (`ua_pe_hourly_consulting`, etc.).
- Three template slots: initiation, termination, invoicing.
- Seed data loaded from `data/hpc_service_agreement_context_types.xml`.

### `hpc.legal.entity.type` / `hpc.payment.method.type`
- Catalogue models used as filter criteria on service agreements.
- Unique code constraint.
- Seeded with `ua_pe`, `individual` / `sepa`, `swift`, `gbp`, `ua_bank_card`, `cash`, `crypto`.

### `hpc.contractor.invoice`
- Per-employee invoice sequence (CINV/ prefix).
- DOCX/PDF generation + Odoo Sign flow.
- Batch operations and ZIP download.

### Additional Inherited Models
- `hpc_salary_run_ext` — adds `contractor_invoice_ids` to salary run.
- `hpc_res_company_ext` — adds representative, Ukrainian company name, payment duration.
- `hpc_res_users_ext` — adds signature image to user.
- `hpc_document_template_ext` — adds category extensions to document templates.
- `hpc_document_template_metadata_default` — metadata key-value defaults.

## Revolut Payments

### `hpc.contract.revolut` (inherits `hr.payroll.contractor.contract`)
- Stores Revolut Business payment details on contracts.
- `is_revolut_enabled` toggle to show/hide fields.

### `hpc.salary.run.revolut` (inherits `hr.payroll.contractor.salary.run`)
- Server action: batch Revolut CSV export.

### `hpc.revolut.export.wizard` (TransientModel)
- Generates Revolut Business CSV for batch payments.
- Payment reference is dynamic: "Payment for invoice {uid} from {date}".

### `account.move` (inherited) — Revolut CSV Export
- `salary_run_id` field links vendor bills back to the salary run that created them.
- Server action "Export for Revolut Batch Payment" on vendor bill list view.
- For bills with `salary_run_id`: uses contract Revolut fields (same logic as salary run export).
- For bills without `salary_run_id`: maps from partner name, bank account (IBAN/BIC), address, and bill amount.

## Ukrainian PE Fields

### `hpc.contract.ua_pe` (inherits `hr.payroll.contractor.contract`)
- Optional section on contract form (`is_ukrainian_pe` toggle).
- 30+ bilingual (UA/EN) fields for:
  - Contract metadata (ID, dates, locations)
  - Personal info in Ukrainian and English
  - Identity document (ID Card or Paper Passport)
  - Tax & PE registration details
  - Payment duration
- Example images for ID card and passport displayed beside fields.

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

### Employee Self-Service Checklist (v1.4.0)

1. As admin: assign `Payroll Contractor Employee` group to an internal user linked to an employee (`hr.employee.user_id` set)
2. Log in as that user: "My Payroll" app appears; full "Payroll for Contractors" does NOT appear (unless also in `group_hpc_user`)
3. Click "My Payroll" app icon → **opens salary runs list directly** (no settings form, no access error)
4. "My Salary Runs": employee sees only their own salary runs; timesheet lines are fully read-only
5. **Employee adjustments**: open a draft or `approved_and_locked` salary run → can add rows to "Addings / Subtractions" with description + amount + attachment; save succeeds; total_to_pay updates; adjustments blocked when `invoiced`
6. **Confirm Compensation**: open an `approved_and_locked` salary run → "Confirm Compensation" button visible → click → button disappears, badge shows "Confirmed by Employee"; `invoiced` runs show no button (already confirmed or confirmed badge shows)
7. **Confirmation reset**: manager unlocks run (→ draft) OR recomputes timesheets → badge resets to "Waiting Employee Confirmation"
8. "My Contracts": only that employee's contracts shown; form is fully read-only
9. As a different employee user: confirm they see only their own records and cannot edit the other employee's adjustments
10. **Manager view (group_hpc_user)**: `employee_confirmation` badge visible in form header and optional tree column
11. **Role rename check**: Settings → Users → Groups → Human Resources/Payroll shows 4 groups: "Payroll Contractor Manager", "Payroll Administrator", "Payroll Timesheets Reviewer", "Payroll Contractor Employee"
12. **Manager CRUD contracts**: user in `group_hpc_user` can create/edit/delete contracts
13. As Timesheets Reviewer (`group_hpc_ts_reviewer`): open salary run form → Payment Calculation Card is not visible; `total_to_pay` column absent in salary runs list

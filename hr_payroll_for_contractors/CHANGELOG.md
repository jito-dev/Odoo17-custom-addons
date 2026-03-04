# Changelog

## 2026-02-28 (v1.2.2)
- Summary: Replaced radio quick-period widget with Bootstrap-styled buttons matching the dashboard look; date fields now default to current month.
- Details:
  - Removed `period_preset` Selection field and `@api.onchange` approach
  - `date_start` and `date_end` now default to first/last day of current month, enabling clean form save before button clicks
  - Added three server methods: `action_period_prev_month`, `action_period_this_month`, `action_period_next_month`
  - View: `d-flex` div with `btn btn-secondary` / `btn btn-primary btn-sm` buttons placed below the period fields, hidden once approved
- Files:
  - `models/hpc_salary_run.py`
  - `views/hpc_salary_run_views.xml`
  - `__manifest__.py`

## 2026-02-28 (v1.2.1)
- Summary: Fixed missing settings_id on standalone salary run creation; added quick period radio buttons (Prev / This / Next Month) to the salary run form.
- Details:
  - `default_get()` override auto-resolves the company settings singleton so `settings_id` is never blank when creating a salary run from any entry point
  - `action_open_salary_runs()` on contract now injects `default_contract_id` + `default_settings_id` into context
  - New non-stored `period_preset` Selection field with `@api.onchange` fills `date_start`/`date_end` instantly, works on unsaved records
  - Period radio buttons hidden once run is approved/locked
- Files:
  - `models/hpc_salary_run.py`
  - `models/hpc_contract.py`
  - `views/hpc_salary_run_views.xml`
  - `__manifest__.py`

## 2026-02-28
- Summary: Added contract state (Active / In Use) with locked core fields, salary run smart button on contracts, and contract status badge on salary run form.
- Details:
  - Contract gains computed `state`: `active` when no salary runs linked, `in_use` once any run exists
  - Core contract fields (employee, type, rate, dates, currency) become read-only when `in_use`
  - Contract form shows smart button counting linked salary runs (opens filtered list on click)
  - Salary run `oe_button_box` gains a "Contract" smart button showing the contract state badge
  - Contract tree view shows state badge and row decorations (green=active, orange=in_use)
  - Search filters added: Active / In Use on the Contracts search view
- Files:
  - `models/hpc_contract.py`
  - `models/hpc_salary_run.py`
  - `views/hpc_contract_views.xml`
  - `views/hpc_salary_run_views.xml`
  - `__manifest__.py`

## 2026-02-27
- Summary: Renamed `locked` state to `Approved & Locked`, added auto-dashboard refresh, monthly period constraint, bill smart buttons, migration hook, and account.move unlink protection.
- Details:
  - State machine changed: `draft → approved_and_locked → invoiced` (was `locked`)
  - "Lock" button renamed to "Approve" (highlighted); adjustments become read-only once approved
  - Dashboard lines auto-refresh every time the Dashboard menu is opened
  - New `@api.constrains` on salary runs: monthly contracts must span a full calendar month
  - Smart button box now shows "No Bill Yet" (clickable to create) when approved without a bill
  - Deleting a linked vendor bill automatically reverts salary run state to `approved_and_locked`
  - `post_migrate_hook` converts existing `locked` DB records to `approved_and_locked` on upgrade
  - New `models/account_move.py` inheriting `account.move` for the unlink hook
- Files:
  - `__manifest__.py`
  - `__init__.py`
  - `hooks.py`
  - `models/__init__.py`
  - `models/account_move.py`
  - `models/hpc_salary_run.py`
  - `models/hpc_settings.py`
  - `views/hpc_salary_run_views.xml`
  - `GUIDANCE.md`

## 2026-02-27
- Summary: Fixed dashboard period display format, blocked salary run deletion when an invoice exists, and updated module icon.
- Details:
  - Dashboard banner now shows human-readable dates: "Feb 1, 2026 – Feb 28, 2026" instead of raw ISO format
  - Added `dashboard_period_label` computed `Char` field driven by `dashboard_date_start/end`
  - `unlink()` override on `hr.payroll.contractor.salary.run` raises `UserError` if a vendor bill is linked
  - Module icon replaced with new salary/payslip illustration
- Files:
  - `models/hpc_settings.py`
  - `models/hpc_salary_run.py`
  - `views/hpc_settings_views.xml`
  - `static/description/icon.png`
  - `__manifest__.py`

# Changelog

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

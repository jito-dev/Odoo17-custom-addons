# Changelog

## 2026-05-09 (v1.5.10)
- Summary: Sign documents attached to a Service Agreement no longer have to be fully signed — any signing state can be attached (in-progress `shared`/`sent`, finished `signed`, or terminal `refused`/`canceled`/`expired`).
- Details:
  - Removed `domain="[('state', '=', 'signed')]"` from `signed_sign_request_ids` on `hpc.contract.service.agreement`. Field name kept as-is for backwards compatibility with the v1.5.8 schema (relation table `hpc_contract_sa_signed_sign_request_rel` unchanged).
  - Notebook tab renamed **Signed Documents → Sign Documents**; help text and inline placeholder updated to reflect that any state is selectable.
  - Inline tree's `state` badge gained `decoration-warning` (sent/shared) and `decoration-danger` (refused/canceled/expired) on top of the existing `decoration-success` (signed).
- Files:
  - `models/hpc_contract_service_agreement.py`
  - `views/hpc_contract_service_agreement_views.xml`
  - `__manifest__.py`
  - `GUIDANCE.md`

## 2026-05-08 (v1.5.9)
- Summary: New `ca_sp` (Canadian Sole Proprietor) entity type for legal entities, with Sole Proprietor data + Identity Document section reusing the existing International Passport fields.
- Details:
  - `hpc.contractor.legal.entity.entity_type` Selection now includes `('ca_sp', 'Canadian Sole Proprietor')`.
  - New fields: `ca_sp_first_name`, `ca_sp_last_name`, `ca_sp_business_name`, `ca_sp_business_id_number`, `ca_sp_tax_id_number`, `ca_sp_principal_address` (Text), `ca_sp_federal_business_number`. Required modifiers (`first_name`, `last_name`, `principal_address`) enforced at the view layer via `required="entity_type == 'ca_sp'"`.
  - `ca_sp_id_doc_type` Selection added with one option (`international_passport`); kept as Selection for forward compatibility. Identity Document section reuses the existing `intl_passport_*` fields — no field duplication.
  - New catalog row `entity_type_ca_sp` (sequence 15) seeded in `data/hpc_service_agreement_context_types.xml`.
  - Three view files updated with the new conditional `<group invisible="entity_type != 'ca_sp'">` block: `hpc_contractor_legal_entity_views.xml` (standalone form), `hpc_contractor_views.xml` (inline o2m), `hpc_employee_portal_views.xml` (read-only portal).
  - `_compute_display_name` updated with the new label.
- Files:
  - `models/hpc_contractor_legal_entity.py`
  - `data/hpc_service_agreement_context_types.xml`
  - `views/hpc_contractor_legal_entity_views.xml`
  - `views/hpc_contractor_views.xml`
  - `views/hpc_employee_portal_views.xml`
  - `__manifest__.py`
  - `GUIDANCE.md`

## 2026-05-08 (v1.5.8)
- Summary: Service Agreement gains an `is_templated` toggle (default True) for one-time SAs and a `signed_sign_request_ids` M2M for attaching already-signed Sign module documents (NDAs, addenda, or the SA itself when not templated).
- Details:
  - New `is_templated` Boolean on `hpc.contract.service.agreement` (tracked). When False the form hides Agreement Template selection, Agreement Terms group, and the Agreement/Termination/Context notebook tabs.
  - `template_id` is no longer `required=True` at field level — replaced by an `@api.constrains` that enforces it only when `is_templated=True`. Existing records keep the default True via Odoo's `_init_column` write of the field default.
  - New `signed_sign_request_ids` Many2many to `sign.request` with domain `[('state', '=', 'signed')]`. Surfaced in a new always-visible **Signed Documents** notebook tab. Coexists with the existing template-driven `agreement_sign_template_id` / `termination_sign_template_id` flow.
  - `action_generate_agreement`, `action_generate_termination`, `action_send_agreement_for_signing`, `action_send_termination_for_signing`, `action_rebuild_context` now call `_ensure_templated()` and raise `UserError` on one-time SAs.
  - Tree view gains optional `is_templated` boolean-toggle column. Search view gains "Templated" / "One-time" filters.
- Files:
  - `models/hpc_contract_service_agreement.py`
  - `views/hpc_contract_service_agreement_views.xml`
  - `__manifest__.py`
  - `GUIDANCE.md`

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

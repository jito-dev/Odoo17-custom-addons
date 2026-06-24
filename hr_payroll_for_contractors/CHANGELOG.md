# Changelog

## 2026-06-24 (v1.6.4)
- Summary: the **Wise US Dollar** method is corrected to a true **domestic USD (ACH)** transfer — the format Revolut Business uses to send a *local* USD payment to a personal Wise USD account (no SWIFT). Verified against current Wise and Revolut help docs.
- Method label: `('ach', …)` now reads **"Wise US Dollar (ACH)"** (internal key stays `ach`). Same rename on the 3 view group titles and the `payment_type_ach` catalogue seed.
- Re-added **`ach_account_type`** (Selection `checking`/`savings`, default **Checking**): Revolut requires the account type for every US ACH beneficiary, and Wise USD accounts are Checking. The DB column from its earlier (v1.6.3) removal is reused cleanly.
- Removed from the UI: **`ach_swift_bic`** — SWIFT/BIC is an international-wire detail, never used for a domestic ACH. The field is kept on the model (dormant) so no data/column is dropped; it is simply no longer shown on any of the 3 ACH groups.
- Field order on all 3 groups is now: Recipient Name → Account Type → Routing Number → Account Number → Bank Name → Bank Address → Currency. `ach_recipient_name` relabelled **Recipient Name** (was "Account Holder").
- Validation unchanged: `@api.constrains` still checks only `ach_routing_number` (9-digit ABA, isolated to `method_type == 'ach'`).
- Tests: `tests/test_ach_payment_method.py` — persistence test updated to the corrected fields; added account-type default (checking) and savings-allowed tests.
- Files: `models/hpc_contractor_payment_method.py`, `views/hpc_contractor_payment_method_views.xml`, `views/hpc_contractor_views.xml`, `views/hpc_employee_portal_views.xml`, `data/hpc_service_agreement_context_types.xml`, `tests/test_ach_payment_method.py`, `__manifest__.py` (1.6.3 → 1.6.4).

## 2026-06-24 (v1.6.3)
- Summary: the **ACH** payment method is renamed **Wise US Dollar** and trimmed to exactly the receiving details a personal Wise USD account hands out — for paying a worker from Revolut Business to their **private** (not business) Wise USD account.
- Method label: `method_type` Selection `('ach', …)` now reads **"Wise US Dollar"** (internal key stays `ach`, so existing records and the document merge fields keep working). Same rename on the 3 view group titles and the `payment_type_ach` catalogue seed.
- Kept fields (the 6 Wise requisites + currency): `ach_recipient_name` (relabelled **Account Holder**), `ach_account_number`, `ach_routing_number` (relabelled **Routing Number**), `ach_swift_bic`, `ach_bank_name`, `ach_bank_address`, and the readonly USD `ach_currency_id`.
- Removed fields (not part of Wise's requisites): `ach_wire_routing_number`, `ach_account_type` (checking/savings), `ach_account_holder_address`. Orphan DB columns are left in place (harmless); none were used by the doc-merge or Create-Vendor flows.
- Validation: `@api.constrains` now checks only `ach_routing_number` (still 9-digit ABA, still isolated to `method_type == 'ach'`).
- Tests: `tests/test_ach_payment_method.py` — dropped the wire-routing tests, updated the persistence test to the kept fields. Suite green **9/9**.
- Files: `models/hpc_contractor_payment_method.py`, `views/hpc_contractor_payment_method_views.xml`, `views/hpc_contractor_views.xml`, `views/hpc_employee_portal_views.xml`, `data/hpc_service_agreement_context_types.xml`, `tests/test_ach_payment_method.py`, `__manifest__.py` (1.6.2 → 1.6.3).

## 2026-06-24 (v1.6.2)
- Summary: **Wise USD receiving-account fields** added to the existing **US Bank Transfer (ACH)** method on `hpc.contractor.payment.method`. Additive only — no new method type, no migration. A Wise USD account is an ACH record plus the extra detail Wise hands out.
- Why: receiving USD into a Wise account requires more than the ACH basics — Wise always lists the partner-bank **address**, can give a separate **wire routing number**, exposes a **SWIFT/BIC** for international (non-US) senders, and some banks want the **account-holder address** for incoming wires.
- New fields: `ach_account_holder_address`, `ach_wire_routing_number`, `ach_swift_bic`, `ach_bank_address`. All optional.
- Validation: the existing `@api.constrains` now also validates `ach_wire_routing_number` as **exactly 9 digits** (same ABA rule as `ach_routing_number`), still isolated to `method_type == 'ach'`. Empty values stay allowed.
- Views: new fields added to all **3 ACH groups** — payment-method form, contractor form (embedded), employee portal (readonly), keeping the three in sync.
- Tests: `tests/test_ach_payment_method.py` extended — wire-routing valid/too-short/non-numeric/empty + a persistence test for all Wise fields. Suite green **13/13** on a clean `-i`.
- ⚠️ Handoff / not in scope: the new fields are **not** yet wired into the "Create Vendor" `res.partner.bank` flow or the document merge fields, and the Revolut CSV export for ACH is still Phase 2.
- Files: `models/hpc_contractor_payment_method.py`, `views/hpc_contractor_payment_method_views.xml`, `views/hpc_contractor_views.xml`, `views/hpc_employee_portal_views.xml`, `tests/test_ach_payment_method.py`, `__manifest__.py` (1.6.1 → 1.6.2).

## 2026-06-22 (v1.6.1)
- Summary: **Bugfix** — a regular (non-HR-Officer) user got `AccessError` ("security restrictions … res.users / read") when opening **My Profile**.
- Root cause: `res.users.read` reads a user's own record under `sudo` only when **every** field on the form is in `SELF_READABLE_FIELDS` (see `odoo/addons/base/models/res_users.py`). This module adds `hpc_signature_img` (+ `hpc_signature_img_filename`) to the My Profile form (`view_users_form_hpc_signature`, inherits `base.view_users_form_simple_modif`) but never registered them, so the read fell back to non-sudo and raised on the officer-only HR fields (birthday, ssnid, passport_id, private_*, …).
- Fix: `hpc_res_users_ext` now extends `SELF_READABLE_FIELDS` / `SELF_WRITEABLE_FIELDS` with both signature fields (calling `super()`), like `hr` core does for its own profile fields. They are the user's own data on their own profile — legitimately self read/write.
- Tests: `tests/test_profile_self_read.py` — fields registered as self read/write, and a non-officer can read its own private HR fields + the signature field together without `AccessError`.
- Files: `models/hpc_res_users_ext.py`, `__manifest__.py` (1.6.0 → 1.6.1).

## 2026-06-12 (v1.6.0)
- Summary: New **US Bank Transfer (ACH)** payment method on `hpc.contractor.payment.method`, designed to integrate natively with Odoo's US localization. Phase 1 (data model + UI + document wiring); Revolut CSV export for ACH is deferred to Phase 2.
- Details:
  - `method_type` Selection gains `('ach', 'US Bank Transfer (ACH)')`. New fields: `ach_recipient_name`, `ach_account_number`, `ach_routing_number` (ABA), `ach_account_type` (checking/savings), `ach_bank_name`, `ach_currency_id` (USD, readonly).
  - `@api.constrains` validates the routing number as **exactly 9 digits**, isolated to `method_type == 'ach'` — no other payment method is re-validated (additive, no migration needed).
  - ACH field group added to **3 views**: payment-method form, contractor form (embedded), employee portal (readonly).
  - **`l10n_us` added to `depends`** so the routing number is stored in the native `res.partner.bank.aba_routing` field (NOT `bank_bic`) by the Create Vendor flow — keeps the data correct and NACHA-ready.
  - **Dedicated document merge fields** so routing is never mislabelled as BIC/SWIFT on a US payment document: service agreement `{{ payment_routing }}`, invoice `{{ invoice_routing }}`. ⚠️ Handoff: add these placeholders to the relevant `.docx` templates for them to print.
  - Catalogue `hpc.payment.method.type` seeded with a new `ach` entry.
  - First unit tests added (`tests/test_ach_payment_method.py`): routing validation + isolation + USD default.
- Files:
  - `models/hpc_contractor_payment_method.py`
  - `models/hpc_contract_service_agreement.py`
  - `models/hpc_contractor_invoice.py`
  - `views/hpc_contractor_payment_method_views.xml`
  - `views/hpc_contractor_views.xml`
  - `views/hpc_employee_portal_views.xml`
  - `data/hpc_service_agreement_context_types.xml`
  - `tests/__init__.py`, `tests/test_ach_payment_method.py`
  - `__manifest__.py`
  - `GUIDANCE.md`

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

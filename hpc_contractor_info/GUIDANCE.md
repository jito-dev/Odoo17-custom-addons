# hpc_contractor_info — Contractors' Info Module

## Purpose

Provides a canonical place for contractor identity and payment data.
Instead of scattering Ukrainian PE fields across individual contracts,
each employee gets **one** `hpc.contractor` record that holds:

- Multiple **Legal Entities** (e.g. Ukrainian Private Entrepreneur, Individual)
- Multiple **Payment Methods** (e.g. Revolut), each optionally linked to a legal entity

## Dependencies

- `hr_payroll_for_contractors` — groups, root menu
- `hr_payroll_ua_pe` — kept as dependency so its contract fields remain without regression

## Models

### `hpc.contractor`
- One record per employee (`unique(employee_id)` constraint)
- `_inherit = ['mail.thread']` for chatter
- Two `One2many` relations: `legal_entity_ids`, `payment_method_ids`

### `hpc.contractor.legal.entity`
- `entity_type` selection: `ua_pe` | `individual`
- All Ukrainian PE fields (identity doc, personal info UA/EN, contract meta, tax/register)
- Identity images stored as binary attachments
- `individual` type shows "To be implemented later." placeholder

### `hpc.contractor.payment.method`
- `method_type` selection: `revolut` (extensible)
- `legal_entity_id` domain-filtered to the parent contractor's entities
- Full Revolut fields: IBAN, BIC, bank/recipient country, address, currency

## Views

- **Contractor form**: `oe_title` + employee field + notebook (Legal Entities | Payment Methods) + chatter
- **Legal Entity inline form**: radio `entity_type` at top; full UA PE section or Individual placeholder
- **Payment Method inline form**: legal entity selector, method selector, Revolut section with logo

## Menus

Menu item `Contractors' Info` appended to `hr_payroll_for_contractors.menu_hpc_root`
at `sequence=15` (between Dashboard and Salary Runs).

## Security

Re-uses groups from `hr_payroll_for_contractors`:
- `group_hpc_user` / `group_hpc_manager` → full CRUD
- `group_hpc_ts_reviewer` → read-only on contractor and legal entity; no access to payment methods

## Contractor Invoices (v1.43.0)

### `hpc.contractor.invoice`
- Created per salary run via "Generate Contractor Invoices" button (state=approved_and_locked)
- **Per-entity sequence**: each `hpc.contractor.legal.entity` gets its own `ir.sequence` (code `hpc.ci.le.{id}`, prefix `CINV/`, created on demand). Falls back to global `CINV/` sequence when no entity is set.
- **Hours calculation** (UA PE Hourly Consulting + Hourly-based SA):
  `hours_on_invoice = total_to_pay / sa.hourly_rate` — only when `sa.template_id.agreement_category == 'ua_pe_hourly_consulting'` and `agreement_type == 'hourly_based'`
- **Payment method** resolved via SA first, then contract fallback
- Context includes SA fields (`sa_reference`, `sa_date_*`, `sa_hourly_rate`, etc.) and address fields (`pe_address_ua`, `pe_address_en`)
- `action_generate_invoice_docs()` — renders DOCX + PDF from `sa.template_id.inv_template_file`; rebuilds context first; marks state=generated
- **Sign flow**: `invoice_sign_template_id` + computed `invoice_sign_request_id`/`invoice_sign_request_state` + `action_send_for_signing()` / `action_view_signing()` / `action_download_signed()` / `action_reset_signing()`
- Employee access: `group_hpc_employee` read-only via `ir.rule` on own records

### `hr.payroll.contractor.salary.run` extension
- `contractor_invoice_ids` O2M + `contractor_invoice_count` smart button
- `action_generate_contractor_invoices()`: creates/updates contractor invoice, reads service_agreement_id from contract
- `action_download_contractor_invoices()`: zips all generated DOCX files (batch action)

## Service Agreement Templates (v1.34.0 / v1.36.0)

### `hpc.service.agreement`
- Singleton per `agreement_category` (currently only `ua_pe_hourly_consulting`)
- `agreement_type` field above the notebook — always visible on all tabs
- `view_category` non-stored computed field drives the H1 category dropdown
- `name` non-stored computed from `agreement_category` — no stale stored value
- 3 computed Boolean fields: `init_uploaded`, `term_uploaded`, `inv_uploaded` — used by stat buttons
- Stat buttons show green "Uploaded" or orange "Missing" for each of the 3 template slots
- Tab 3: "Contractor Invoicing"; separators: "Template Variables" / "Filename Variables"
- "Required Context" sections: `acceptable_entity_type_ids` (M2M → `hpc.legal.entity.type`) in Tab 1;
  `acceptable_payment_type_ids` (M2M → `hpc.payment.method.type`) in Tab 3
- Seed data: `ua_pe`, `individual` entity types; `sepa`, `swift`, `gbp`, `ua_bank_card`, `cash`, `crypto` payment types
- `post_migrate_hook` populates defaults (ua_pe + sepa/swift) on existing records and cleans up stale menus/actions

## Contract Integration (v1.36.0)

- `hr.payroll.contractor.contract` gains `service_agreement_id` (Many2one → `hpc.service.agreement`)
  replacing the old `invoicing_logic_id` and `legal_relationship_ids` fields
- "Open Service Agreement ↗" button opens the SA form in a dialog (`target: 'new'`)
- **Removed models** (DB tables remain as orphaned — harmless): `hpc.legal.relationship`,
  `hpc.invoicing.logic`, `hpc.legal.relationship.metadata`, `hpc_sign_request_ext`
- **Removed menus**: "Legal Relationships", "Invoicing Logics", "Docs Templates"
  (cleaned up in `post_migrate_hook` via `env.ref(...).unlink()`)

## Important Notes

- The existing UA PE fields on `hr.payroll.contractor.contract` remain untouched (backward compat).
- Static images reused from `hr_payroll_ua_pe` and `hpc_revolut_payments` modules via their paths.
- `sign` module dependency re-added in v1.40.0 to support Send for Signing flow.

## Service Agreement Document Generation (v1.40.0)

### New fields on `hpc.contract.service.agreement`
- `context_data` (Text) — JSON audit trail of the last built context
- `agreement_docx_id` / `agreement_pdf_id` / `agreement_sign_template_id` — for Agreement (initiation)
- `termination_docx_id` / `termination_pdf_id` / `termination_sign_template_id` — for Termination

### Methods
- `_build_context()` — builds a Jinja2 context dict from SA fields (legal entity, payment method,
  SA terms, company data). Saves JSON to `context_data`. Mirrors `hpc_contractor_invoice.action_build_context()`.
- `_generate_docs(template_file_field, basename)` — renders DOCX via `docx_renderer.render_docx()`;
  also calls `convert_to_pdf()` if LibreOffice is available.
- `action_generate_agreement()` / `action_generate_termination()` — trigger generation for each document type.
- `action_send_agreement_for_signing()` / `action_send_termination_for_signing()` — create a
  `sign.template` from the PDF and open Odoo Sign's template editor via `ir.actions.client` tag `sign.Template`.
- `action_download_*()` — force-download helpers (act_url with `?download=true`).

### Sign Flow
1. Generate Agreement (or Termination) → DOCX (and PDF if LibreOffice present) are stored as `ir.attachment`.
2. Click "Send for Signing" → `sign.template` is created; Odoo Sign editor opens pre-loaded with the PDF.
3. User places signature fields and dispatches signing request. The `sign_template_id` field links back.


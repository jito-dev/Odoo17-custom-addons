# hr_payroll_ua_pe — Ukrainian PE Info on Contractor Contracts

## What This Module Does

Extends the `hr.payroll.contractor.contract` model with a collapsible **Ukrainian PE Info**
section for Ukrainian Private Entrepreneurs (ФОП). The section holds bilingual (UA/EN) legal
data required for service contracts: full names, patronymics, registered addresses, identity
documents, VAT/ITN, and PE register extract details.

## Depends On

- `hr_payroll_for_contractors` — provides the base `hr.payroll.contractor.contract` model.

## Main Model

**`HpcContractUaPe`** (`models/hpc_contract_ua_pe.py`)
`_inherit = 'hr.payroll.contractor.contract'`

### Field Groups

| Group | Fields |
|---|---|
| Enable flag | `is_ukrainian_pe` (Boolean toggle) |
| Contract meta | `ua_contract_id`, `ua_contract_conclusion_date`, `ua_contract_location_ua/en`, `ua_pay_duration` |
| Personal — UA | `ua_pe_last_name_ua`, `ua_pe_first_name_ua`, `ua_pe_by_father_ua`, `ua_pe_sex`, `ua_pe_address_ua` |
| Personal — EN | `ua_pe_last_name_en`, `ua_pe_first_name_en`, `ua_pe_address_en` |
| Identity doc | `ua_id_doc_type` + ID Card fields (`ua_id_card_*`) + Passport fields (`ua_passport_*`) |
| Tax / Register | `ua_vat_itn`, `ua_register_extract_number`, `ua_register_extract_date` |

## View

**`views/hpc_contract_ua_pe_views.xml`** inherits `hr_payroll_for_contractors.view_hpc_contract_form`
and appends the Ukrainian PE section after `compensation_group`.

Key UX patterns:
- `<separator string="Ukrainian PE Info"/>` + `boolean_toggle` widget for `is_ukrainian_pe`.
- Entire content block: `invisible="not is_ukrainian_pe"` — collapses when unchecked.
- ID Card vs. Paper Passport fields toggle via `invisible="ua_id_doc_type != 'id_card'"` /
  `invisible="ua_id_doc_type != 'paper_passport'"`.

## Security

No new security files — the module inherits all access rules from `hr_payroll_for_contractors`.
Users/managers who can edit contracts can also edit the UA PE fields.

## Important Constraints

- All UA PE fields are optional; none are required at the model level (business validation
  is handled at document-generation time if DocGen is added later).
- The section is intentionally company/customer-data-free — that data is managed elsewhere.

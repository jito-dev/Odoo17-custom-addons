# hpc_revolut_payments

## Purpose

Extends contractor contracts with Revolut Business payment details and provides a CSV batch-payment export from salary runs.

## Dependency

Requires `hr_payroll_for_contractors` to be installed first.

## Relation to the other Revolut modules

This module makes **no API call and gets no status feedback**: the CSV is uploaded to Revolut
Business by a human, and Odoo never learns whether the batch was executed. The only confirmation is
the outgoing payment reappearing as a `revolut.transaction` (type `transfer`) on the next Business
API sync in `legacy_accounting_helper`, where it is injected as a bank statement line and reconciled
against the payable.

`payment_revolut` (Merchant API, customers paying invoices by card) is unrelated to both. All three
flows end to end: the Obsidian note `obsidian/Projects/Odoo-Revolut-Payment-Module/11-Revolut-Flows-End-to-End.md`.

## What It Does

### 1. Payment Details on Contract

Adds a **"Payment Details for Revolut Business"** section to the Contractor Contract form view:

| Field | Description |
|---|---|
| `revolut_recipient_name` | Legal entity name of the recipient |
| `revolut_iban` | IBAN for the bank account |
| `revolut_bic` | BIC/SWIFT code |
| `revolut_bank_country_id` | Country of the recipient's bank (ISO 2-letter code) |
| `revolut_recipient_country_id` | Country of the recipient (ISO 2-letter code, may differ from bank country) |
| `revolut_address_line1` | Street address line 1 |
| `revolut_address_line2` | Street address line 2 (optional) |
| `revolut_city` | City |
| `revolut_postal_code` | Postal / ZIP code |

The existing `currency_id` from the contract is displayed read-only inside the section.

### 2. Revolut Batch Payment CSV Export

A server action **"Export for Revolut Batch Payment"** is available on the Salary Runs list view (Action menu).

- Select one or more salary runs → Action → Export for Revolut Batch Payment
- A wizard dialog opens with a download link for `revolut_batch_payment.csv`
- The CSV matches the Revolut Business bulk-payment format

**CSV columns**: Name, Recipient type, IBAN, BIC, Recipient bank country, Currency, Amount, Payment reference, Recipient country, Address line 1, Address line 2, City, Postal code

## Architecture

- `models/hpc_contract_revolut.py` — adds Revolut fields to `hr.payroll.contractor.contract` via `_inherit`
- `models/hpc_salary_run_revolut.py` — adds `action_export_revolut_csv()` to `hr.payroll.contractor.salary.run` via `_inherit`
- `models/hpc_revolut_export_wizard.py` — `TransientModel` that generates the CSV on `create()`
- `views/hpc_contract_revolut_views.xml` — injects the Payment Details section into the contract form
- `views/hpc_revolut_export_wizard_views.xml` — wizard dialog form
- `views/hpc_revolut_server_action.xml` — server action bound to the salary run list view
- `security/ir.model.access.csv` — ACL for the wizard (group_hpc_user)

## Security

- The Payment Details section and the export action are gated by `group_hpc_user` (Payroll Contractor Manager + Administrator).
- `group_hpc_ts_reviewer` and `group_hpc_employee` cannot see or use the export.

## Patterns & Constraints

- Both country fields use `ondelete='restrict'`.
- CSV `Amount` is formatted as `'%.2f'` (no currency symbol).
- `Recipient type` is hardcoded to `COMPANY`.
- `Payment reference` is hardcoded to `Payment for Software Development Work`.

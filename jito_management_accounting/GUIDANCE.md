# Management Accounting Module

## Purpose
Provides a parallel management accounting ledger on top of Odoo's financial accounting.
Enables internal profitability analysis, reclassification, allocation, and reporting
without altering statutory accounting data.

## Terminology
- **Classification** = labeling existing financial data with management accounts (automated via rules or manual via "Classify" button)
- **Management Journal Entry** = creating management-only balanced entries that don't exist in financial accounting (e.g., internal charges, DeFi income, transfer pricing)
- **Allocation** = splitting amounts from one management account across multiple targets
- **Timing Adjustment** = spreading/deferring/accelerating across periods

## Main Models

### Configuration
- **mgmt.config** - Singleton settings (ingestion preferences, default currency)
- **mgmt.account.group** - Hierarchical grouping for management accounts (_parent_store)
- **mgmt.account** - Management chart of accounts (code, name, type, group)
- **mgmt.account.mapping** - Default classification (financial-to-management account fallback)

### Period Management
- **mgmt.period** - Lifecycle: draft -> open -> closed. Independent from financial lock dates.

### Ingestion & Ledger
- **mgmt.source.line** - Ingested references to account.move.line with denormalized snapshots. States: draft (unclassified) / processed (classified).
- **mgmt.ledger.line** - Central artifact. All processing outputs land here with origin traceability.

### Rules & Processing
- **mgmt.mapping.rule** - Sequenced classification rules (first-match-wins). Match by account, journal, partner, label, product, analytics, date, amount. Supports single-target or multi-target split.
- **mgmt.mapping.rule.line** - Multi-target split lines (percentage-based).
- **mgmt.allocation.rule** / **mgmt.allocation.rule.line** - Split amounts by percentage or fixed amount
- **mgmt.timing.rule** - Straight-line spread, defer, or accelerate across periods

### Management Journal Entries
- **mgmt.manual.adjustment** / **mgmt.manual.adjustment.line** - Balanced double-entry with mandatory reason. For entries that don't exist in financial accounting.
- **Journal Types**: general (default), receivable, payable. Receivable/payable require a partner and auto-default the first line account from config.
- Dedicated menus: "Crypto Receivables" / "Crypto Payables" filter by journal_type.

### Multi-Target Classification Rules
- **mgmt.mapping.rule.line** - When a classification rule has target_line_ids, the source amount is split proportionally across multiple management accounts.
- Percentages must sum to 100%. Last line gets the remainder to avoid rounding drift.
- Optional partner_id override per split line.

### Effective Date Override
- Optional **Effective Date** on the Classify wizard (wizard-level + per-line).
- Cascade: line effective date → wizard effective date → source line date.
- Wizard-level: sets the default for all lines. Per-line (optional column "Eff. Date"): overrides for that specific line.
- Use case: vendor bills spread over months that actually represent a single-month salary — set the wizard-level effective date to concentrate all lines into one month. Or split one bill across two dates using per-line overrides.
- Defaults to empty (uses source date). An info banner appears when the wizard-level date is set.

### Reference Currency
- **ref_currency_id** / **ref_amount** on ledger lines, MJE lines, and classify wizard lines — tracks the economic currency when it differs from the booking currency (e.g., paying EUR but underlying value is in USD/crypto).

### Matching
- **mgmt.ledger.line.matching_number** - Lines matched together share a matching number (MM/00001)
- **mgmt.match.wizard** - Select 2+ unmatched lines → match (assigns number). If unbalanced, creates write-off line (origin_type='matching')
- Cross-account matching allowed
- "Open Items" view = unmatched ledger lines (matching_number is False)
- Unmatch: clears matching_number, deletes write-off lines

### Management Analytics
- **mgmt.analytic.plan** — dimension categories (e.g., "Department", "Service Type", "Cost Center"). Admin-managed under Configuration.
- **mgmt.analytic.account** — values within a plan (e.g., "UX/UI Design", "Software Development → Outsource"). Supports parent/child hierarchy via `_parent_store`. Display name includes plan (e.g., "Department / UX/UI Design").
- Lines are tagged via `mgmt_analytic_account_ids` (Many2many, displayed as tags). Constraint: max one account per plan per line.
- **Analytics Picker** (`mgmt.analytic.picker`) — popup wizard showing one row per plan with account dropdown and percentage. Opens via "Set Analytics" button. Pre-fills from existing M2M, writes back on Apply.
- **Analytic Split**: On ledger lines, adding multiple rows for the same plan (e.g., Department: UX 60%, Dev 40%) splits the ledger line proportionally. Cross-product when multiple plans have splits. Original line deleted, N new lines created with proportional amounts. Matched lines must be unmatched first.
- Present on: ledger lines (with split), MJE lines, classification rules (simple M2M only).
- Classification rules carry default analytics; multi-target lines can override per-split.
- Allocation does NOT carry analytics (pooled amounts make source analytics ambiguous).

### Project Tracking
- `project_id` (Many2one project.project) on ledger lines, MJE lines, classify wizard lines, and classification rules.
- Passed through in all creation flows (classify, MJE post, mapping rules).
- Groupable in ledger search view.

### Reconciliation
- **mgmt.reconciliation** / **mgmt.reconciliation.line** - Financial vs management variance by account

## Ingestion Filters
The Ingest Source Data wizard supports these filters (all optional, empty = include all):
- **Status**: Posted (validated) toggle, Reconciled toggle
- **Journals**: Multi-select specific account.journal records
- **Financial Accounts**: Multi-select specific account.account records
- **Entry Type**: Preset groups (All, Invoices & Bills, Customer Invoices, Vendor Bills, Journal Entries, Receipts)
- **Partners**: Multi-select specific res.partner records
- **Analytic Accounts**: Multi-select specific analytic accounts (filters by JSON analytic_distribution)
- **Exclude Zero-Balance**: Skip lines where debit=credit=0

## Processing Pipeline
1. **Ingest** source data from account.move.line (via wizard with filters)
2. **Classify** source lines to management accounts (via classification rules, then default classification fallback, or manual "Classify" button)
3. **Allocate** amounts across management accounts (via allocation rules)
4. **Timing** adjustments (spread/defer/accelerate)
5. **Management Journal Entries** (balanced entries for management-only data)
6. **Reconcile** financial vs management totals
7. **Report** via pivot/graph views on mgmt.ledger.line

## Undo / Reset
- **Single ledger line**: "Unclassify" button (classification lines only)
- **Single source line**: "Reset to Draft" button
- **Bulk**: Select multiple source lines → Actions → "Reset Selected to Draft"
- **Period-wide**: "Reset Classification" / "Reset Allocations" buttons on period form

## Menu Structure
```
Management Accounting
├── Ledger
│   ├── Management Ledger
│   ├── Open Items (unmatched lines)
│   └── Source Lines
├── Operations
│   ├── Periods
│   ├── Management Journal Entries
│   ├── Crypto Receivables (filtered MJE)
│   ├── Crypto Payables (filtered MJE)
│   ├── Timing Adjustments
│   └── Reconciliation
├── Reporting
│   └── Partner Reports
│       └── Partner Ledger (account_reports engine, PDF/XLSX export)
├── Configuration
│   ├── Settings
│   ├── Chart of Accounts
│   │   ├── Management Accounts
│   │   ├── Account Groups
│   │   └── Default Classification
│   ├── Rules
│   │   ├── Classification Rules
│   │   └── Allocation Rules
│   └── Analytics
│       ├── Analytic Plans
│       └── Analytic Accounts
```

## Key Constraints
- Financial accounting data is IMMUTABLE from this module (read-only references only)
- Every management ledger line has an origin_type and traceability back to source
- Period locking is independent from financial lock dates
- Management journal entries must be balanced (debit = credit) and include a reason
- Closed periods prevent any modifications to their ledger lines

## Security
- **group_mgmt_user** - Read-only access to all management accounting data
- **group_mgmt_admin** - Full CRUD, configuration, period management, journal entries
- Company isolation via ir.rule on all models

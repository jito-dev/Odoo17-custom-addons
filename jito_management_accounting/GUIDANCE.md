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
- **mgmt.mapping.rule** - Sequenced classification rules (first-match-wins). Match by account, journal, partner, label, product, analytics, date, amount.
- **mgmt.allocation.rule** / **mgmt.allocation.rule.line** - Split amounts by percentage or fixed amount
- **mgmt.timing.rule** - Straight-line spread, defer, or accelerate across periods

### Management Journal Entries
- **mgmt.manual.adjustment** / **mgmt.manual.adjustment.line** - Balanced double-entry with mandatory reason. For entries that don't exist in financial accounting.

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
│   └── Source Lines
├── Operations
│   ├── Periods
│   ├── Management Journal Entries
│   ├── Timing Adjustments
│   └── Reconciliation
├── Configuration
│   ├── Settings
│   ├── Management Accounts
│   ├── Account Groups
│   ├── Default Classification
│   ├── Classification Rules
│   └── Allocation Rules
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

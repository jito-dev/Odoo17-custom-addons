# jito_ledger_core — Developer Guidance

## Module Purpose

`jito_ledger_core` is **Phase 1** of the management-ledger feature
(see [`docs/HLD.md`](../../docs/HLD.md)). It is the foundation every
later module depends on:

- Defines the **`jito.ledger`** configuration model — the record that
  identifies a ledger as Leading or Non-Leading.
- Defines the **`jito.ledger.account`** model — the **management-layer
  chart of accounts**, fully separate from stock Odoo's `account.account`
  (HLD Decision #13).
- Defines the **`jito.ledger.journal.rel`** join table that links
  `jito.ledger` to stock `account.journal` *without modifying
  `account.journal`* (HLD Decision #9).
- Adds a **`@constrains`** validator on `jito.ledger.account.code`
  enforcing the FAAP / MGT semantic-prefix policy
  (HLD §4.4). Stock `account.account` is **not** validated and is
  left strictly untouched.
- Ships the four **`group_mgmt_ledger_*`** security groups described
  in PRD §Security Matrix.
- Exposes a **standalone top-level "Management Ledger" menu** — not
  nested under stock Accounting (HLD Decision #14).
- Provides a **`post_init_hook`** that seeds a set of example
  statutory-aligned management accounts and an example Bank journal for
  each existing company **into `jito.ledger.account`** (HLD Decisions
  #2 + #13). No bare structural root accounts are seeded — the CoA is a
  flat list (grouping is by `account_type` and account codes).

This module ships **no model for journal entries** — those live in
`jito_ledger_nl` (Phase 2).

---

## Architecture Overview

### Two charts of accounts

The system holds two parallel charts of accounts:

| Chart | Model | Owner | Codes | Notes |
|---|---|---|---|---|
| Statutory | `account.account` | Stock Odoo | Tenant-defined (e.g., `1200`, `7000`, `IBAN-EUR`) | **Untouched by this module.** |
| Management | `jito.ledger.account` | This module | `FAAP.<statutory number>` / `MGT.<statutory number>` | New table; semantic-prefix policy enforced. |

Management codes are **statutory-aligned numeric** codes: the prefix is
followed by the bare statutory number (e.g. `MGT.400500`, `FAAP.101401`).
A FAAP.\* record may carry a soft pointer (`statutory_account_id`) to a
stock `account.account` for combined-view reporting (Phase 5). MGT.\*
records do **not** point at the statutory chart.

### Why a separate management-layer CoA?

The first cut of Phase 1 mixed FAAP/MGT accounts into `account.account`.
After install, user feedback flagged two problems:

1. **Statutory accountants saw unfamiliar codes** in their day-to-day
   chart of accounts.
2. **Stock Odoo behaviour drifted** — adding a `@constrains` on
   `account.account` changed validation for codes that touched our
   prefixes, even if a tenant had a coincidentally-named code.

Decision #13 (HLD §11) closes this: management-layer accounts live in
their own table; stock Odoo's chart is read-only from our side.

### Why a join table for journals?

Per HLD Decision #9, the user's strongest-form architectural rule is
"no schema change to Odoo accounting models." Adding a `ledger_id` FK to
`account.journal` would violate that. The join table costs one tiny
model and preserves the rule as load-bearing rather than aspirational.

### Why a standalone UI?

Per HLD Decision #14: the management-ledger feature has its own
personas (CFO, Senior Accountant, Accountant, ERP Admin) and is not a
sub-section of stock Accounting. A top-level "Management Ledger" menu
makes that explicit. Stock Accounting workflows stay visually
unchanged.

---

## Main Models

### `jito.ledger`

**File:** `models/jito_ledger.py`

**Purpose:** Identifies and configures a ledger.

**Key fields:**
| Field | Type | Notes |
|---|---|---|
| `name` | Char (required) | Display name. |
| `code` | Char (required) | Short identifier. Unique per company. |
| `kind` | Selection (required) | `leading` / `non_leading`. |
| `company_id` | Many2one `res.company` (required) | Owning company. |
| `journal_rel_ids` | One2many `jito.ledger.journal.rel` | The journals associated with this ledger. |
| `journal_ids` | Computed Many2many `account.journal` | Convenience read-only mirror. |
| `active` | Boolean | Standard archive flag. |

**Constraints:**
- `_check_single_leading` — at most one `leading` per company (FR-01).
- `_check_single_non_leading` — at most one `non_leading` per company
  in v1 (FR-03).
- SQL UNIQUE on `(code, company_id)`.

**Mixins:** `mail.thread` for chatter / audit log.

### `jito.ledger.account`

**File:** `models/jito_ledger_account.py`

**Purpose:** Management-layer chart of accounts.

**Key fields:**
| Field | Type | Notes |
|---|---|---|
| `code` | Char (required, indexed) | Must start with FAAP/MGT and be UNIQUE per company. Statutory-aligned: prefix + bare statutory number (e.g. `MGT.400500`). |
| `base_code` | Char (computed, stored, indexed) | The bare statutory number after the prefix (e.g. `MGT.400500` → `400500`). Used to align FAAP/MGT pairs to the same statutory number and for report roll-up. |
| `name` | Char (required, translatable) | Display name. |
| `account_type` | Selection (required) | Same selection as stock `account.account` (asset_receivable, equity, income, expense, off_balance, etc.) so reports can group accounts using familiar conventions. |
| `is_clearing` | Boolean (editable, default from account_type) | Marks the account as a clearing / suspense / transit account. Meaningful on MGT accounts; AR/AP and clearing accounts default `reconcile=True`. A journal's `suspense_account_id` is domain-filtered to `[('is_clearing','=',True)]`. |
| `company_id` | Many2one `res.company` (required) | Owner. |
| `currency_id` | Many2one `res.currency` (optional) | Force account currency, mirroring stock `account.account.currency_id`. |
| `statutory_account_id` | Many2one `account.account` (optional, ondelete='set null') | FAAP.* mirrors only; cross-references the statutory account this account projects. |
| `semantic_family` | Selection (computed, stored, indexed) | Derived from the code's prefix: `faap` / `mgt`. Used by reports. |
| `active` | Boolean | Standard. |

**Constraints:**
- `@constrains('code')` — must start with one of `FAAP.` / `MGT.`,
  with non-empty body and no whitespace.
- `@constrains('semantic_family', 'statutory_account_id')` —
  `statutory_account_id` is allowed only on FAAP.* accounts.
- SQL UNIQUE on `(code, company_id)`.

**Mixins:** `mail.thread`.

**Module-level constants** (importable by downstream modules):
- `SEMANTIC_PREFIXES = ('FAAP.', 'MGT.')`
- `_split_prefix(code)` helper.

### `jito.ledger.journal.rel`

**File:** `models/jito_ledger_journal_rel.py`

**Purpose:** Links one `account.journal` to at most one `jito.ledger`.

**Key fields:**
| Field | Type | Notes |
|---|---|---|
| `ledger_id` | Many2one `jito.ledger` (required) | ondelete=cascade. |
| `journal_id` | Many2one `account.journal` (required) | ondelete=restrict. |
| `company_id` | Many2one (related, stored, indexed) | From `ledger_id`. |

**Constraints:**
- SQL UNIQUE on `journal_id` — a journal belongs to at most one ledger.
- `_check_journal_company` — same-company.

### Stock `account.account` — UNCHANGED

This module **does not extend** `account.account`. No fields are added,
no constraints, no methods overridden. Stock Odoo's chart of accounts
behaves exactly as today.

---

## Business Logic

### Semantic prefix policy (HLD §4.4)

The two families act as a logical namespace within the
**management-layer** chart. Both use statutory-aligned numeric codes
(`FAAP.<statutory number>` / `MGT.<statutory number>`):

- `FAAP.*` — default projection of statutory account meaning. Mirrors
  exist for each LL account that is consumed by management reporting.
- `MGT.*` — final managerial / economic meaning. The terminus of
  Bridging and Restatement adjustments.

**Clearing accounts** are no longer a separate family. Clearing is a
per-account boolean flag `is_clearing` on `jito.ledger.account`
(meaningful on MGT accounts). Clearing accounts are transit-only:
postable **only from mgt_bridge / mgt_restate entries** (constraint
enforced in Phase 2). A journal points at its clearing account via its
existing `suspense_account_id`, whose domain is now
`[('is_clearing','=',True)]`.

**Grouping / consolidation** is no longer a separate family either.
Reporting roll-up is driven by `account_type` and account codes (the
CoA is a flat list) — there is no non-posting grouping-node family.

Constraint locus: `jito.ledger.account.code` only. Stock
`account.account.code` accepts any string as Odoo ships it.

### Auto-seeded Leading Ledger record (PRD §Vocabulary)

Per PRD vocabulary, every company has **exactly one** Leading Ledger,
and it is "the main accounting ledger… mandatory for all companies."
For us, the Leading Ledger is stock Odoo accounting; the
`jito.ledger(kind=leading)` record is just a **label** for stock Odoo
accounting in this company.

`hooks.py::_ensure_leading_ledger_for_company` creates this label
record on install (and on the 17.0.1.1.3 upgrade migration for tenants
who had earlier versions). Defaults: `name="Leading Ledger"`, `code="LL"`,
`kind="leading"`. Tenants may rename freely. The record is deletable.

### Seeded chart of accounts (HLD Decisions #2 + #13)

`hooks.py::post_init_hook` runs once on module install. It iterates
every `res.company` and creates, **in `jito.ledger.account`**, a set of
example management accounts. The `SEEDED_ROOTS` list holds
`(code, name, account_type, is_clearing)` 4-tuples:

| Code | Type | `is_clearing` | Comment |
|---|---|---|---|
| `MGT.101401` | `asset_cash` | no | "Bank (example — connect a DeFi wallet)". |
| `MGT.101402` | `asset_cash` | no | "DeFi Wallet (example)". |
| `MGT.101900` | `asset_current` | **yes** | "Clearing / Suspense (example)"; transit-only clearing account. |
| `MGT.132000` | `asset_receivable` | no | "Account Receivable". |
| `MGT.211000` | `liability_payable` | no | "Account Payable". |
| `MGT.400500` | `income` | no | "Product Sales". |
| `MGT.600500` | `expense` | no | "Operating Expenses". |

No structural root accounts are seeded. The former `FAAP.ROOT` /
`MGT.ROOT` anchors (and the older `CLR.ROOT` / `GRP.ROOT`) are
**dropped** — the CoA is a flat list with no parent/child hierarchy;
clearing is the `is_clearing` flag and grouping is by
`account_type` and account codes. The former named buckets
`MGT.SALES` / `MGT.EXPENSE` / `MGT.RECEIVABLE` / `MGT.PAYABLE` are
renamed to `MGT.400500` / `MGT.600500` / `MGT.132000` / `MGT.211000`
respectively.

The hook also seeds one **example Bank journal** per company (code
`CBANK`, type `bank`) with `bank_account_id = MGT.101401` and
`suspense_account_id = MGT.101900` (the clearing account).

Idempotent: an existing record with the same code in the same company
is left alone. Companies created **after** module install do not get
the seed automatically — operators may run a Server Action that calls
`_ensure_roots_for_company(env, company)` from `hooks.py`. Automating
new-company seeding is a v1.x improvement.

### Migration from prior versions (17.0.1.0.x → 17.0.1.1.0)

Prior versions seeded roots into stock `account.account` and
extended that model with a `@constrains`. Both have been removed.
`migrations/17.0.1.1.0/post-migrate.py` runs on upgrade and:

- searches `account.account` for codes `FAAP.ROOT`, `MGT.ROOT`,
  `CLR.ROOT`, `GRP.ROOT`;
- **deletes** them only if they have **zero journal items** (safe);
- **leaves them alone with a warning log** if any have been used.

The seed for the new model (`jito.ledger.account`) is created by the
post-init hook of the new version, but the post-init hook **does not**
re-run on upgrade — Odoo only calls it on first install. Operators
upgrading from a buggy prior install therefore need to either:
- Uninstall and reinstall the module (the cleanest path), or
- Manually run the helper from a Server Action / console:
  `from odoo.addons.jito_ledger_core.hooks import post_init_hook; post_init_hook(env)`

### Account categories removed (17.0.6.0.0)

The user-defined `jito.ledger.account.category` roll-up layer was fully
removed in 17.0.6.0.0. The `jito.ledger.account.category` model, the
`category_id` field on `jito.ledger.account`, the
`jito.ledger.account.category.add.wizard`, the "Account Categories"
configuration menu / views / ACLs, and the
`report_handler_base._bucket_accounts_by_category` helper (in
`jito_ledger_reports`) are all gone. Account grouping is now driven
purely by account **codes** and `account_type` — the CoA is a flat
list and there is no separate category roll-up.

### Single-leading and single-non-leading invariants

FR-01: every company has at most one Leading Ledger. FR-03: at most one
Non-Leading Ledger per company in v1. Both enforced by `@constrains` on
`jito.ledger`.

---

## Security

### Group hierarchy (per PRD §Security Matrix)

```
base.group_system
  ↑ implies
group_mgmt_ledger_admin
  ↑ implies
group_mgmt_ledger_senior_accountant ──> group_mgmt_ledger_accountant
group_mgmt_ledger_finance_manager  ──> group_mgmt_ledger_accountant
                          ↑ implies
                  account.group_account_manager
                          ↑ implies (via accountant)
                  account.group_account_user
```

### ACLs

`security/ir.model.access.csv`:

| Model | Accountant | Senior Acct. | Finance Manager | Admin |
|---|---|---|---|---|
| `jito.ledger` | read | read | read | full |
| `jito.ledger.journal.rel` | read | read | read | full |
| `jito.ledger.account` | read | read+write+create | read+write+create | full |

The chart of accounts (`jito.ledger.account`) is editable by Senior
Accountant and FM (matching their authority over chart structure in
stock Odoo); only the admin can hard-delete entries.

### Record rules

`security/record_rules.xml` — multi-company scoping on all three new
models. A user only sees records in their `company_ids`.

**LL immutability is enforced at the schema level**, not via record
rules — no `jito_ledger_*` table holds an FK into `account.move*`.

---

## Views & Menus

### Standalone application menu

Per HLD Decision #14:

```
Management Ledger              (top-level, sequence=95)
├── Ledgers                    (action: jito.ledger)
└── Chart of Accounts          (action: jito.ledger.account)
```

The menu is visible to all four `group_mgmt_ledger_*` groups. There is
**no** integration into Accounting → Configuration. Stock Accounting
workflows are visually unchanged.

### Files

- `views/jito_ledger_views.xml` — tree, form, search for `jito.ledger`.
- `views/jito_ledger_account_views.xml` — tree, form, search for
  `jito.ledger.account`. Form has a "Statutory Cross-Reference" group
  visible only on FAAP.* records.
- `views/menus.xml` — top-level menu + 2 submenus.

Per project CLAUDE.md, all tree views use `<tree>` (not `<list>`).

---

## Integration Guidelines

### For downstream modules (Phase 2 onwards)

- **Look up a ledger** by `(company_id, kind)`.
- **Phase 2's `jito.ledger.move.line.account_id`** must reference
  `jito.ledger.account`, **not** `account.account`.
- **Reuse `SEMANTIC_PREFIXES` and `_split_prefix()`** from
  `models/jito_ledger_account.py`. Don't re-encode the prefix list.
- **The seeded roots + example accounts** (incl. the `CBANK` bank
  journal) are guaranteed to exist per company **on install**.
- **Pick clearing accounts** via `is_clearing = True`, not a prefix;
  a journal's clearing pointer is its `suspense_account_id`.
- **Constraints on `jito.ledger.account`** are already in place;
  downstream modules should not duplicate them.

### For tenant operators

- After install, the example management accounts appear under
  **Management Ledger → Chart of Accounts** per company, alongside an
  example `CBANK` bank journal.
- Stock Odoo's Chart of Accounts under **Accounting → Configuration**
  is unchanged.
- Create a `jito.ledger(kind=leading)` for each company first (a label
  for "stock Odoo accounting in this company"), then optionally a
  `jito.ledger(kind=non_leading)`.
- Associate `account.journal` records to ledgers via the Ledgers form's
  Journals tab.

---

## Verification Checklist (Phase 1)

After installing or upgrading:

1. **DB migration succeeds** — install/upgrade completes without errors.
2. **No mgmt codes in stock CoA** — Accounting → Configuration → Chart of
   Accounts: search for `MGT.` / `FAAP.` → **none should appear**.
3. **Seeded mgmt-layer accounts exist** — Management Ledger → Chart of
   Accounts: the example accounts (`MGT.101401`, `MGT.101402`,
   `MGT.101900`, `MGT.132000`, `MGT.211000`, `MGT.400500`, `MGT.600500`)
   are present per company, and **no** `*.ROOT` anchor accounts.
   `MGT.101900` has `is_clearing = True`. An example `CBANK` bank
   journal exists with `suspense_account_id = MGT.101900`.
4. **Standalone menu** — top-level "Management Ledger" menu visible
   alongside Sales, Inventory, Accounting, etc. Two submenus: Ledgers,
   Chart of Accounts.
5. **Ledger creation** — Management Ledger → Ledgers → New; create
   `non_leading`. Try a second `non_leading` for the same company →
   rejected.
6. **Single-leading constraint** — try a second `leading` → rejected.
7. **Mgmt-layer CoA validator** —
   - `FAAP.` (empty body) → rejected
   - `FAAP.101 401` (whitespace) → rejected
   - `FAAP.101401` → accepted (statutory-aligned numeric code)
   - `MISC.123` (no semantic prefix) → **rejected** (every record in
     `jito.ledger.account` must use a `FAAP.` / `MGT.` prefix; this
     differs from the prior implementation which validated
     `account.account`).
   - `base_code` on `MGT.400500` → computes to `400500`.
8. **Stock CoA unaffected** —
   - `MISC.123` in **stock** Accounting → Configuration → Chart of
     Accounts: **accepted** (no jito constraints there).
9. **FAAP statutory pointer** — the seed ships only `MGT.*` accounts, so
   open any of them (e.g. `MGT.400500`): the "Statutory Cross-Reference"
   group is **hidden**. After running **FAAP Mirrors → Sync**, open a
   generated `FAAP.*` account: the group is **visible**.
10. **Journal association** — open NL ledger → Journals tab → add a
    journal → save. Try the same journal on a second ledger → SQL
    UNIQUE error.
11. **No regression in stock Accounting** — Accounting → Customers →
    Invoices works exactly as before.
12. **Migration cleanup (upgrade only)** — if upgrading from
    17.0.1.0.x, the four orphan accounts in `account.account` are
    removed (or skipped with a warning if they had journal items).
    Check the server log for `jito_ledger_core 17.0.1.1.0:` lines.

---

## Out of scope (deferred)

- Ledger-specific currency / fiscal-year overrides — v1 inherits from
  company per FR-03.
- Approval workflow for ledger or chart configuration changes — out of
  scope per PRD FR-19.
- Auto-seeding of root accounts for companies created **after**
  install — operators run the helper manually for now.
- LL immutability via record rule — explicitly schema-level only here.
- Top-level menu icon — default Odoo icon for v1; styled icon in v1.x.

For the rest of the v1 trajectory, see `docs/HLD.md` §3 and the plan at
`docs/PRD.md` / `docs/Specification.md`.

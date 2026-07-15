# Upwork Simple Accounting — Module Guidance

## What This Module Does

Integrates Upwork with Odoo via OAuth2 to:
1. Authenticate with Upwork using Authorization Code Grant
2. Select an Upwork organization and auto-detect the accounting entity ID
3. Download the full transaction ledger (transactionHistory GraphQL query)
4. Display all transaction fields in a rich detail viewer
5. Generate DOCX/PDF invoices from transaction data using Jinja2 templates

> **Note:** Beyond the data viewer / document generator, the module also **injects** transactions into Odoo accounting as bank statement lines with mapped GL counterparts (see *Subtype → GL Account Mapping* below). It depends on the `account` module.

---

## Module Structure

```
upwork_simple_accounting_integration/
├── controllers/upwork_oauth.py             # /upwork/callback OAuth2 route
├── models/
│   ├── usa_organization.py                 # Cached Upwork org list
│   ├── usa_settings.py                     # Singleton config + API logic
│   ├── usa_transaction.py                  # Transaction rows + invoice gen + invoice PDF
│   ├── usa_invoice_config.py               # Invoice DOCX template config
│   └── usa_upwork_invoice_upload.py        # TransientModel wizard: bulk PDF upload & match
├── views/
│   ├── usa_settings_views.xml              # Two focused forms: Upwork Config + Transaction Sync
│   ├── usa_transaction_views.xml           # Transaction tree + form (inc. Upwork Invoice tab)
│   ├── usa_invoice_config_views.xml        # Invoice config standalone form
│   ├── usa_upwork_invoice_upload_views.xml # Wizard form + window action
│   └── usa_menus.xml
└── security/
    ├── security.xml                        # Groups: Admin + Accountant
    └── ir.model.access.csv
```

---

## Main Models

### `usa.settings` — Singleton
One global record. Contains:
- OAuth credentials (key, secret, callback_url, access_token, refresh_token, token_expiry)
- Selected organization (Many2one → usa.organization)
- Accounting entity ID (auto-loaded via GraphQL)
- Sync period (sync_date_start, sync_date_end) + last_sync_date
- All API logic: connect, load orgs, load entity, sync transactions

Two standalone focused views (no tabs):
- `view_usa_settings_upwork_form` — OAuth credentials, connection, org, entity
- `view_usa_settings_ledger_form` — sync period, sync button, stats

All action methods that return `ir.actions.act_window` for `usa.settings` include `view_id` to ensure the correct focused view is rendered after the action.

### `usa.organization` — Org Cache
Populated from `companySelector` GraphQL query. Cleared and recreated on each "Load Organizations" call.

### `usa.transaction` — Transaction Row
One record per `recordId` from Upwork API. All fields from `transactionHistoryRow`. Includes:
- Full raw JSON in `raw_json` field
- Invoice generation fields: `invoice_state`, `generated_docx_id`, `generated_pdf_id`
- Jinja2 context builder: `action_build_invoice_context()`
- Doc generator: `action_generate_invoice()`
- AI extraction state tracking: `extraction_state` (idle/pending/processing/done/failed), `extraction_status`

### AI Data Extraction — Job Queue Pattern
Single-record button (`action_extract_data_from_invoice`) runs synchronously — fine for 1 record.
Batch action (`action_batch_extract_data_from_invoice`) uses `queue_job`:
1. Sets all selected records to `extraction_state = pending`
2. Enqueues one `_run_extract_job(user_id)` job per record via `with_delay()`
3. Returns immediately — UI is not blocked
4. Each job independently calls `_extract_data_from_invoice_core()`, sets state to `processing` → `done`/`failed`
5. On completion, sends a `bus.bus` notification to the originating user

Requires: `queue_job` and `bus` in module depends.

### `usa.upwork.invoice.upload` — TransientModel Wizard
Bulk-uploads Upwork PDF invoices and auto-matches each to a `usa.transaction` record:
- `attachment_ids` (Many2many ir.attachment, `widget="many2many_binary"`) — files dropped/selected by user
- `action_upload()` — iterates attachments, extracts `T<record_id>` from filename via regex, writes PDF binary + filename to matched transaction
- Returns a `display_notification` action summarising matched/unmatched counts
- Both roles have full CRUD access (transient records are auto-cleaned by Odoo)

### `usa.invoice.config` — Singleton
Holds the DOCX invoice template (Binary field). Uses `jito_document_template` for:
- Jinja2 variable detection from uploaded .docx
- Rendering with `render_docx()` and optionally `convert_to_pdf()`

---

## OAuth Flow

1. Admin sets API Key + Secret in Configuration → Upwork Configuration
2. The `callback_url` is computed **live** as `{web.base.url}/upwork/callback` (non-stored — see Important Patterns)
3. Click **Connect with Upwork** → opens Upwork authorization in new tab
4. User authorizes → Upwork redirects to `/upwork/callback?code=XYZ`
5. Controller (`controllers/upwork_oauth.py`) exchanges code for tokens
6. Tokens stored in `usa.settings` singleton
7. Connection status badge updates to "Connected"

## GraphQL Queries

All calls go to `https://api.upwork.com/graphql` with:
- `Authorization: Bearer {access_token}`
- `X-Upwork-API-TenantId: {organization_id}` (when org is selected)

Queries: `companySelector`, `accountingEntity`, `transactionHistory`

## Upwork Invoice PDF Upload

1. Download Upwork PDF invoices (filenames contain `T<record_id>`)
2. Menu → **Upload Upwork Invoices** → drag & drop PDFs in the dialog
3. Click **Upload & Match** — each PDF is matched by Record ID and stored on the transaction
4. Open transaction → **Upwork Invoice** tab → PDF renders inline via `pdf_viewer` widget
5. Unmatched files are listed in the result notification

**Filename pattern:** `2026-03-15_...-LIS_T899387936_invoice.pdf` → Record ID `899387936`

## Invoice Generation

1. Upload .docx template in Configuration → Invoice Generation
2. Open a transaction → Invoice Generation tab
3. Click **Generate Invoice** — builds context dict from transaction fields
4. Renders via `jito_document_template` service: `render_docx()` + `convert_to_pdf()`
5. Stores DOCX + PDF as `ir.attachment` on the transaction

**Context objects available in template:**
- `transaction` — all transaction identification and date fields
- `amount` — all monetary amounts with currencies
- `assignment` — agency, company, developer, team IDs

---

## Roles & Permissions

| Role | Access |
|------|--------|
| **Upwork Simple Accounting Administrator** | Full access: config, OAuth, sync, invoice generation |
| **Accountant** | Ledger + transactions only; cannot see Configuration tab or menu |

---

## Accounting Injection (v1.6.0)

### Overview
Bridges `usa.transaction` → Odoo accounting by creating `account.bank.statement.line` records. Uses `transaction_amount_raw` (gross amount) — Upwork fees appear as separate ledger rows, so the net effect is correct and fees are individually trackable.

### Configuration
- **Configuration → Mapping to Odoo Accounting**: select the Odoo bank journal for Upwork transactions.
- Journal stored on the `usa.settings` singleton (`journal_id` field).

### Key Fields on `usa.transaction`
- `statement_line_id` (Many2one → account.bank.statement.line): links to injected entry.
- `is_injected` (Boolean, computed/stored): True when `statement_line_id` is set.
- `upwork_tx_ref` (Char, computed/stored, trigram-indexed): equals `record_id` — stored on both the transaction and the statement line for traceability.

### Key Methods
- `action_inject_to_accounting()`: batch-creates statement lines. Skips already-injected and zero-amount rows. Best-effort partner matching by `assignment_company_name`. Multi-currency support.
- `action_remove_from_accounting()`: unreconciles if needed, resets to draft, deletes the move.
- `_find_partner_for_transaction()`: searches `res.partner` by client company name.

### Statement Line Extension
- `upwork_tx_ref` (Char) on `account.bank.statement.line` — set during injection.
- `upwork_tx_ref` (related, stored) on `account.move.line` — visible as optional column in Journal Items.

### UX Flow
1. Configuration → Mapping to Odoo Accounting → select bank journal.
2. Transactions → select rows → Actions → **Inject to Accounting**.
3. To undo: select rows → Actions → **Remove from Accounting**.
4. Single-record: form view has Inject/Remove buttons in the header.

> Note: the injector uses `amount_credited_raw` (the **signed** wallet movement), not `transaction_amount_raw` — this keeps the Upwork Wallet balance correct (withdrawals/membership/VAT have opposite signs between the two columns).

---

## Subtype → GL Account Mapping (v1.8.0)

Each injected `account.bank.statement.line` now posts its **counterpart** to a mapped GL account
instead of landing in the journal suspense account.

### Model `usa.account.map` (Injection Rules)
- Key: `(company_id, transaction_type, accounting_subtype)` — unique. Blank `accounting_subtype` acts as a per-type wildcard.
- `account_id` → counterpart `account.account`. `tax_id` is reserved/stored but **not** applied in v1 (taxes deferred).
- Surfaced inline on **Configuration → Mapping to Odoo Accounting** and via a standalone **Configuration → Injection Rules** list.

### Lookup — `usa.settings._get_account_for_transaction(tx)`
Exact `(type, subtype)` → `(type, blank)` wildcard → `default_counterpart_account_id` (settings) → empty (Odoo posts to suspense; surfaced as a count in the inject notification).

### Tracing an injected transaction (v1.8.1)
`usa.transaction.move_id` (related→`statement_line_id.move_id`, stored) links to the created
`account.move`. The form shows a **Journal Entry** smart button (`action_view_journal_entry`) plus
Journal Entry / Bank Statement Line / Mapped GL Account fields (visible once injected); the tree has
optional **Journal Entry** and **GL Account** columns. Open the entry to see its journal items.

### How the counterpart is posted
`action_inject_to_accounting` adds the magic key `counterpart_account_id` to the
`account.bank.statement.line.create()` vals — Odoo core pops it and builds the non-liquidity move line
on that account, then auto-posts (Odoo `account/models/account_bank_statement_line.py`). Idempotency
(`statement_line_id`/`upwork_tx_ref`/dedup) and `action_remove_from_accounting` are unchanged.

### One-click setup — `action_setup_upwork_accounting()` ("Setup Upwork Accounting" button)
Idempotent (`_ensure_account` reuses any account with the same code per company; a type mismatch is
logged, never overwritten). Creates the dedicated 13-account 6-digit block (`UPWORK_ACCOUNT_SET`), the
**Upwork Wallet (USD)** bank journal (code `UPWK`, default account `101410`), and seeds the 13 default
rules (`UPWORK_SEED_RULES`). Sets `journal_id`, `upwork_wallet_account_id`, `default_counterpart_account_id`.

### Accounts created (dedicated 6-digit block)
`101410` Wallet · `101710` Cash in Transit · `101720` Funding (clearing) · `131500` Input VAT ·
`400500/400510/400590` revenue (hourly/fixed/refunds) · `450500/450510/450520` other income
(bonus/reimbursed/other) · `600500/600510/600520` expense (service fee/membership/withdrawal fee).

### Notes & caveats
- **Withdrawals** → `101710` and **ARPayment funding** → `101720` are *clearing* accounts: reconcile/reclassify them later against the real main-bank line (withdrawal) or to Director's Loan / internal transfer (card vs bank funding). Verified: each `ARPayment` pairs 1:1 with a same-day `ARInvoice`, so it is **funding, not an expense** — no double-count.
- **VAT** → plain posting to `131500` (no tax code) per the "skip taxes for now" decision; it will not auto-feed the VAT return.
- **Single-company**: `usa.settings` is a global singleton; rules carry `company_id` (defaults to `env.company`). Fine for one Upwork org; multi-company would need per-company settings.

---

## Multi-page PDF ingestion & document posting (v1.9.0)

### Bulk PDF split & route
`usa.transaction._ingest_upwork_document(filename, pdf_bytes)` (models/usa_pdf_ingest.py) is the **single**
entry point; both `controllers/upload_invoices.py` and the `usa.upwork.invoice.upload` wizard delegate to it.
It splits an Upwork PDF by **page count** (and, for 3-page docs, by the **matched-tx type**) and routes each kept
page (as its own single-page PDF) to the matching transaction's `upwork_invoice_pdf`:

| Pages | Matched tx | Type | Kept pages → target |
|------|------|------|---------------------|
| 3 | APInvoice / APAdjustment | service delivered | p2 → **Customer Invoice** on the invoice tx · p3 → **Vendor Bill** on the linked Service-Fee tx (`related_transaction_id == invoice.record_id`) |
| 3 | ARInvoice / ARPayment | card payment (Connects/Membership) | p2 → reference on the Membership-Fee tx · p3 → reference on the linked ARPayment tx (`ARPayment.related_transaction_id == membership.record_id`). **Card-paid → parked in suspense `101720` (gl), no vendor bill** (see below). |
| 2 | — | Upwork charge | p2 → **Vendor Bill** on the matched tx (balance-paid membership/connects) |
| 1 | Withdrawal / Withdrawal Fee | transfer summary | the single page → **both** the Withdrawal tx and its linked Withdrawal-Fee (`fee.related_transaction_id == withdrawal.record_id`); **reference only**, no accounting document (gl-mode). Else flagged. |
| ≥4 | — | — | **skipped** (`bad_pagecount`) |

**Card-paid Connects/Membership vs balance-paid** — a `Membership Fee` ARInvoice is card-paid **iff** an
`ARPayment` points back at it (`ARPayment.related_transaction_id == membership.record_id`); 26 of 188 are card-paid.
`usa.settings._is_card_paid_membership` detects this and overrides both the posting mode (→ `gl`) and the
counterpart account (→ the ARPayment/Payment account, `101720`) so the charge and its card receipt land in the same
suspense account and **net to zero on the wallet**, pending manual reclassification (corporate-card match vs
Director's Loan / write-off). The funding source (corporate vs personal card) is ambiguous, so nothing is
auto-expensed and **no vendor bill** is created. Balance-paid memberships (no linked ARPayment) are unaffected and
still become Vendor Bills. *Follow-up:* a card-paid membership's `ARInvoice/VAT` (if any) still maps to `131500`;
connects VAT is reverse-charged (0) in samples — revisit only if real VAT appears.

Page 1 (summary) is always dropped. The filename `T<id>` resolves the primary tx (record_id → related_invoice_id).
Stored filenames: `upwork_<record_id>_<role>_<client>.pdf`. The service↔fee link is **`related_transaction_id`**
(NB: `related_invoice_id` is empty on fee rows). Result dict per file: `{status, doc_type, routed[], message}` —
surfaced in the OWL uploader's results table.

### Posting modes (usa.account.map.posting_mode)
- `gl` — bank line posts straight to the mapped counterpart account (withdrawals, funding, VAT, withdrawal fee…).
- `customer_invoice` — Hourly / Fixed / Milestone / Bonus (3-page service docs): bank line → suspense, revenue via a **Customer Invoice** (out_invoice) reconciled against the wallet inflow.
- `vendor_bill` — Service Fee / Membership: bank line → suspense, expense via a **Vendor Bill** (in_invoice) reconciled against the outflow. **The bill is built entirely from the transaction data** (`_create_vendor_bill_from_upwork_invoice`): amount = `abs(transaction_amount_raw)`, account = mapped `600500`/`600510`, vendor = Upwork, dates = review-due. **No PDF digitizing** — the Upwork PDF is attached for reference only (`register_as_main_attachment` is called with `skip_ai_extract=True`; the AI module `jito_invoice_extract_ai` honors that context). This replaced the old AI extraction, which mis-read amounts (e.g. the 10% fee read as the gross base → **10× bills**, left partially reconciled, and made accrual ≠ cash-basis P&L). Because the amount now equals the wallet line exactly, bills **fully reconcile**. *(The separate optional **client-address enrichment** still uses OpenAI to read the client's billing address off the PDF — the one datum the Upwork API doesn't provide — see Client enrichment.)*
- `customer_refund` — Refund: a **Customer Credit Note** (out_refund) reconciled against the refund outflow.
- `vendor_refund` — a Service-Fee *return* (positive Service Fee linked to a Refund): a **Vendor Credit Note** (in_refund) reconciled against the fee-return inflow.

**Sign rule** — `_get_posting_mode_for_transaction` flips invoice↔credit-note by the signed wallet amount:
a *positive* `vendor_bill` line becomes `vendor_refund`; a *negative* `customer_invoice` line becomes `customer_refund`.
So the same `(APAdjustment, Service Fee)` rule yields a **bill** when charged (−) and a **credit note** when returned (+).
A refund document (3-page) uses the same split path as a service doc — p2 → the Refund tx (customer credit note),
p3 → the linked Service-Fee *return* (vendor credit note). Refund docs are built in `models/usa_refund_creation.py`.

### "Date" = Upwork ledger date (review-due) everywhere
The module treats **`transaction_review_due_date`** as *the* "Date": it's the tx-list **Date** column, the model
`_order` (default sort), and the search **Date** filter / **This Month** / **Group By → Date**. Creation date is
kept as a secondary **Creation Date** column/filter/group-by. (`transactionReviewDueDate` is fetched by the sync and
mapped at `usa_settings.py`.)

### Accounting date = Upwork ledger date (review-due)
On the customer invoice / vendor bill / credit note, **both** the document date (`invoice_date`) **and** the
**Accounting Date (`account.move.date`)** are forced to the review-due date — the Accounting Date is what determines
the reporting period/ledger, so forcing it (not just `invoice_date`) guarantees the journal entry posts in Upwork's
period even if Odoo/AI would otherwise derive a different `date`.

Odoo postings use **`transaction_review_due_date`** (fallback: creation date, then today) as their accounting date,
via `usa.transaction._get_accounting_date()` — used by the injected **bank statement line** and by the
**customer invoice / vendor bill / credit note** (`invoice_date`). Reason: Upwork's ledger **"Date"** column is the
review-due (availability) date — when the transaction posts to the Upwork balance after the ~5-day review hold —
**not** the creation date (the earnings period-end, ~5 days earlier). Verified against a full export: Upwork "Date"
== Review Due Date on **1473/1473** rows, vs only 285 for creation date. For vendor bills the review-due date is
**forced** (it overrides any date the AI extraction read from the PDF) so the bill matches the bank line. The
tx-list **"Date"** column still shows creation date; add the **Review Due Date** column to see the ledger date.
*Existing (already-posted) entries keep their original creation-date postings — re-dating them is a separate,
opt-in operation.*

### Analytic rule engine (extra dimensions, e.g. Department)
Beyond the baseline **Data Source = Upwork**, a small rule engine assigns *additional* analytic plans by matching
the **source transaction**. Rules live in `usa.analytic.rule` (Configuration → **Analytic Rules**), each row =
`match_field` (Freelancer / Client / Agency / Team / Subtype / Tx Type) `match_operator` (`=` / `contains`)
`match_value` → **plan + analytic account**. Example: *Freelancer = "Polina Rudenko" → Department / UX/UI Design*.
- **Setup** seeds a **Department** plan + accounts *Software Development* / *UX/UI Design* (`_ensure_upwork_analytic`,
  `models/usa_analytic_tagging.py`); rules themselves are user-configured (none seeded).
- **Processor** = `account.move._usa_apply_analytics` / `_usa_apply_analytics_to_move` (`models/account_move.py`):
  for each Upwork move it resolves one account per managed plan — Data Source baseline + the **first matching rule
  per plan** (by `sequence`) evaluated against the linked `usa.transaction` (`_usa_linked_transaction`) — and writes
  them onto **all** lines, **clearing** prior managed-plan tags first (idempotent; re-running after a rule change
  re-tags cleanly). "First match per plan wins"; rows with no value for the matched field (connects/membership/
  withdrawal fees have **no freelancer**) don't match, so they stay untagged for that plan.
- **Triggers:** auto **on post** (`_post`, "on row injection") and the **Re-apply Analytic Tags** button
  (`action_backfill_upwork_analytic`), which enqueues **queue_job** background jobs in batches of 200
  (`_usa_reapply_analytics_batch`) — re-tagging thousands of moves is too heavy for one HTTP request. Move→
  transaction is resolved in **one bulk query** (`_usa_resolve_transactions`), not a search per move. **Requires the
  queue_job runner** (`server_wide_modules = …,queue_job` + `[queue_job] channels`); without it the jobs stay
  `pending`. Track under Settings → Technical → Queue Jobs.
- Matching uses `tx.filtered_domain([(field, op, value)])`. To add a person/department, add a rule and click
  Re-apply. (This engine is the natural "prompt2rules" surface — rules are plain `match_field/op/value` rows.)

### Upwork reporting ring-fence (analytic dimension)
A dedicated analytic plan **"Data Source"** with an analytic account **"Upwork"** lets you view *only* Upwork
across **any** Accounting report: filter by **Analytic = Upwork** in the P&L, Balance Sheet, General Ledger,
Partner Ledger, etc. (multi-select-ready — add other sources later, group by the plan).

- **Created** in `action_setup_upwork_accounting` (`_ensure_upwork_analytic`, `models/usa_analytic_tagging.py`),
  stored on settings (`upwork_analytic_plan_id` / `upwork_analytic_account_id`).
- **Auto-tagged** by `account.move._post` (`models/account_move.py`): a move is "Upwork" iff **any line posts to a
  dedicated Upwork account** (`_upwork_account_ids` = the `UPWORK_ACCOUNT_SET` codes for the company). For such
  moves, **every** line's `analytic_distribution` gets `{Upwork: 100}` — *both sides*, so the receivable / payable /
  wallet / VAT lines are tagged too. That full-line coverage is what makes the **Balance Sheet** (not just the P&L)
  ring-fence correctly. Tagging happens while the move is still draft, so `super()._post()` generates the analytic
  lines once. Idempotent + merge-preserving of any other analytic plan.
- Covers every Upwork move type — customer invoices, vendor bills, credit notes, the **wallet bank statement
  moves**, reconciliation write-offs (they land on the Upwork suspense), and the reclassification JE — because all
  of them touch an Upwork account. Even hand-posted entries on the Upwork accounts get tagged.
- **Backfill** existing history with the **Backfill Upwork Analytic** button
  (`action_backfill_upwork_analytic`) — tags all lines of every move touching an Upwork account.
  `analytic_distribution` is editable on posted entries, so analytic lines are regenerated without reset/repost.
- **Caveats:** the Balance Sheet "Current Year Earnings" synthesised line can't be perfectly ring-fenced; a single
  hand-entry mixing Upwork + non-Upwork lines would be tagged wholesale (avoid by keeping Upwork entries on the
  dedicated/suspense accounts); USD-only, so reconciliation forex-difference moves don't arise.

### Expense-account remediation (historical bills)
Before the `_apply_mapped_expense_account` fix, all Service-Fee and Membership vendor bills posted their expense to
the generic `600000` Expenses account (AI-extraction default) instead of `600500` / `600510`. The settings →
**Mapping to Odoo Accounting** form has a **Reclassify Fee/Membership Expenses** button
(`action_reclassify_upwork_expense_accounts`, `models/usa_expense_reclassify.py`) to repair them:
- **Draft** bills → the expense line is re-pointed to the mapped account in place.
- **Posted** bills → a single balanced reclassification journal entry (Dr mapped / Cr `600000`, aggregated per
  account) is created as **draft** in the general journal and opened for review/posting; the original bills and
  their bank reconciliation are untouched.
- **Idempotent** via an `account.move.usa_reclassified` flag (`models/account_move.py`) — handled bills are
  skipped on re-run.

Document modes prevent double-counting (P&L recognised once, via the document, not also on the bank line).
The injector (`action_inject_to_accounting`) only sets `counterpart_account_id` when mode is `gl`.

### Customer-invoice pipeline (models/usa_customer_invoice_creation.py)
Mirrors the vendor-bill pipeline. `_create_customer_invoice_from_service_pdf` builds an `out_invoice` straight
from transaction data (amount/client/date — authoritative), partner via `_find_or_create_customer_partner`
(`customer_rank=1`), revenue line at the mapped account, page-2 PDF as main attachment.
`_auto_reconcile_customer_invoice` reconciles the receivable line against the wallet **inflow** statement line
(mirror of `_auto_reconcile_bill`, `asset_receivable` instead of `liability_payable`). Form buttons + smart
button are gated by `injection_mode`.

### Operator runbook
For transactions already injected under the old direct-GL behaviour, switch to document mode by:
**Remove from Accounting → re-inject (now to suspense) → upload the split PDF → Create Customer Invoice / Vendor Bill → reconcile.**
**Remove from Accounting is a full undo** — it deletes the bank statement line *and* every linked document (vendor bill, customer invoice, customer/vendor credit notes), unreconciling first (`_ACCOUNTING_DOC_FIELDS` / `_remove_document_move`).
Re-running **Setup Upwork Accounting** re-asserts the seed posting modes on un-customised rules.
**Refunds** are handled as credit notes (customer_refund / vendor_refund). `Reimbursed (Expense)` and
`Miscellaneous` revenue currently stay `gl` (TBD — pending review of their document structure).

## Client address enrichment (v1.10.0)

The Upwork API lacks client billing addresses; the service-invoice PDF has them. `models/usa_client_enrichment.py`
(`_inherit='usa.transaction'`) runs the existing OpenAI extraction (`_extract_data_from_invoice_core`) **at most
once per address-less client** and writes street / zip / country onto the client `res.partner` (fill-empty only).

- **Cost gate:** `_partner_needs_address(partner)` = no `street` **and** no `country_id` (covers a card that already
  exists but is empty). Clients with an address are skipped forever.
- **De-dup:** `res.partner.upwork_address_enrich_state` (`none/pending/done/failed`) is set to `pending`
  *synchronously* when a job is queued, so a batch of many invoices for one new client queues only one extraction.
- **Two triggers:** bulk list action **"Enrich Client Addresses"** (`action_enrich_client_addresses` — groups one
  rep per client; already-extracted → fills now with no AI call; else queues `_run_enrich_client_job` via `queue_job`),
  and an auto path in `_create_customer_invoice_from_service_pdf` gated by `usa.settings.auto_enrich_clients` (default off).
- **Write:** `_write_partner_address` fills only empty fields, maps country via `_match_country` (res.country code→name),
  posts a chatter note `"Billing address filled from Upwork invoice T<record_id>"`, marks the partner `done`.
- `_find_or_create_customer_partner` now enriches both found and created partners (incl. `country_id`).
- Requires the **queue_job worker** running for the async path; the sync path (already-extracted rows) needs no worker.

## Important Patterns

- Singleton pattern: `lock_field = Char(default='global')` + `UNIQUE(lock_field)` SQL constraint
- `callback_url` is a **non-stored** computed field derived from `web.base.url`. It is never persisted, so a production→test DB restore can never leave the OAuth `redirect_uri` pointing at the old domain. To override the host, change the `web.base.url` system parameter (the canonical Odoo mechanism) — there is intentionally no manual edit / "reset" button.
- Token refresh: automatic via `_refresh_access_token()` when token is within 1 minute of expiry
- Transaction upsert: search by `record_id` → write if exists, create if not
- Dates from API: ISO8601 with offset `+0000` normalized to UTC before storage

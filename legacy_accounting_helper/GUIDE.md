# Revolut Business API Integration — Module Guide

## What This Module Does

Provides a single-page UI wizard inside Odoo for completing the Revolut Business API OAuth2 setup flow. All six steps are laid out top-to-bottom on one scrollable form view.

Technical module name remains `legacy_accounting_helper` for backward compatibility.

## Main Model

**`legacy.accounting.config`** (`models/legacy_accounting_config.py`)

- Singleton per company (created on first access via `action_open_config()`).
- Stores all state between sessions (not a TransientModel).

## Five-Step Flow

### 1. Add Your Certificate
- Click **Generate / Regenerate Certificates** to create an RSA 2048-bit private key and a proper X.509 self-signed certificate accepted by Revolut.
- Uses `openssl genrsa` + `openssl req -new -x509` via subprocess (requires `openssl` in PATH).
- Public IP is fetched from `api.ipify.org` automatically.
- Download `publiccert.cer` and upload it to your Revolut Business API settings.
- Both **Public Certificate** and **Private Key** fields show a **Copy** button for easy clipboard copying.

### 2. Generate a Client Assertion
- Fill in **iss** (your domain, e.g. `yourdomain.com`) and **sub** (your Revolut `client_id`).
- The JWT payload is computed automatically and displayed full-width; adjust expiry days as needed.
- Click **Generate client_assertion** — this signs the JWT with your private key using RS256.
- The **Client Assertion** field includes a **Copy** button for easy use in API calls.

### 3. Consent to the Application
- Open the **Consent URL** in a browser while logged into Revolut Business.
- After granting access, paste the `code=` value from the redirect URL into **Authorization Code**.

### 4. Exchange Authorization Code for Access Token
- Click **Get Access Token** — POSTs to `https://b2b.revolut.com/api/1.0/auth/token`.
- Raw JSON response is stored; access/refresh tokens are parsed out automatically.
- Use **Refresh Token** to renew the access token without re-authorizing.

### 5. Try Your First API Request
- Click **Test Revolut Business API** — GETs `https://b2b.revolut.com/api/1.0/accounts`.
- Raw JSON response is stored for inspection.

### 6. Token Maintenance
- Visible after Step 4 is complete.
- **Refresh Access Token** — forces token renewal via `action_refresh_token()` (POST with `client_id` in body).
- **Refresh If Expired** — probes `GET /accounts`; refreshes only on HTTP 401; shows "still valid" info if 200.
- Displays current `access_token`, `token_expiry_display`, `refresh_token`, and last refresh raw response.

## Revolut Transactions & Receipts

**`revolut.transaction`** (`models/revolut_transaction.py`)

- Syncs all Revolut Business transactions per company via **Sync All from Revolut** button.
- Stores denormalised primary leg values (amount, currency, description) for fast list rendering.
- `invoice_attachment_ids` (Many2many → `ir.attachment`) stores receipt files explicitly attached by the user.

### Staged Fetch Flow (v1.28.0)

**`revolut.fetched.receipt`** (`models/revolut_fetched_receipt.py`):
- Staging model for receipts downloaded from Revolut but not yet attached to the transaction.
- Fields: `transaction_id`, `attachment_id` (Many2one → ir.attachment), `revolut_expense_id`, `revolut_receipt_id`, `name`, `mime_type`, `is_attached`.
- `action_preview()`: opens `/web/content/{attachment_id}` in a new tab.
- `action_attach()`: adds `attachment_id` to `transaction_id.invoice_attachment_ids`, sets `is_attached=True`.
- `unlink()`: automatically deletes orphaned `ir.attachment` records (those not yet attached).

**Key methods on `revolut.transaction`**:
- `_fetch_and_stage_revolut_receipts(token)`: downloads from Revolut API, creates `revolut.fetched.receipt` + orphan `ir.attachment` records. Sets `revolut_fetch_performed=True`. Silent — never raises UserError (errors are logged).
- `action_fetch_revolut_staged()`: form-view button handler. Clears old staged receipts, re-fetches fresh. Raises UserError if no access token.
- `action_auto_fetch()`: called by JS on every form open; skips if already performed; swallows all errors.
- **Actions menu (list view)**:
  - *Fetch Attachments from Revolut* — batch receipt fetch with per-record bus notifications (direct attach, no staging).
  - *Remove Attachments* — bulk-removes all invoice attachments from selected transactions.

### Auto-fetch on Form Open (v1.28.0)

`static/src/js/revolut_auto_fetch.js` patches `FormController`:
- When a `revolut.transaction` form is opened (or navigated to via pager), calls `action_auto_fetch` via ORM.
- After the call, reloads the model root so results appear immediately.
- Errors are swallowed — the form always loads even if auto-fetch fails.

## Google Gmail Integration (v1.25.0)

### Overview
Users can search their Gmail inbox and attach email attachments directly to Revolut transactions.

### New Models

**`google.credentials`** (`models/google_credentials.py`)
- Stores per-user Google OAuth2 tokens: `access_token`, `refresh_token`, `token_expiry`, `google_email`.
- Methods: `_get_valid_access_token()` (auto-refreshes via `_refresh_access_token()`), `set_tokens()`, `disconnect()`.
- Config params used: `google_gmail_client_id`, `google_gmail_client_secret`.

**`res.users` extension** (`models/res_users.py`)
- Adds `google_account_id` Many2one → `google.credentials` with unique SQL constraint.

**`revolut.gmail.attachment`** (`models/revolut_gmail_attachment.py`)
- Stores found Gmail attachments per transaction (One2many from `revolut.transaction`).
- Fields: `gmail_message_id`, `gmail_attachment_id`, `name`, `mime_type`, `size_display`, `email_subject`, `email_from`, `email_date`, `is_attached`, `is_ai_selected`, `ai_selection_reason`.
- `action_attach()`: downloads the file from Gmail API, creates `ir.attachment`, links to transaction.
- `is_ai_selected` / `ai_selection_reason`: set by `action_ai_analyze()` on the transaction; highlighted green in the tree view.

### New Wizard

**`google.account.manager`** (`wizards/google_account_manager.py`)
- TransientModel for connecting/disconnecting Google accounts.
- Stores Client ID / Secret via `ir.config_parameter`.
- `action_connect_google()` opens Google consent URL (popup).
- OAuth callback handled by `controllers/google_auth.py` at `/google/gmail/callback`.

### Revolut Transaction Changes

New fields on `revolut.transaction`:
- `gmail_search_keywords`, `gmail_search_date`, `gmail_search_range` (default 3 days), `gmail_search_with_attachment`.
- `gmail_search_performed`, `gmail_search_results_count`, `gmail_search_results_html`.
- `gmail_found_attachment_ids` (One2many → `revolut.gmail.attachment`).
- `google_user_connected` (computed non-stored Boolean, checks current user's credentials).

New methods:
- `action_gmail_search()`: builds Gmail query, calls Gmail API `messages.list`, creates `revolut.gmail.attachment` records, renders email card HTML.
- `action_gmail_clear()`: unlinks all found attachments, resets search state.
- `action_ai_analyze()` (v1.27.0): sends transaction details + all found attachment metadata to OpenAI chat completions; marks matching rows with `is_ai_selected=True` and stores the reason. Requires OpenAI config for the company.

### UX Flow
1. Menu → **Google / Gmail Setup** → enter Client ID + Secret → Connect Google Account.
2. Open a transaction → Supporting Documents tab → Gmail Lookup section.
3. Date is auto-filled from transaction `created_at`; enter optional keywords.
4. Click **Search Gmail** → email cards appear + found attachments listed below.
5. Click **AI Analyze** → OpenAI selects best-matching attachments; rows highlighted green with reason text.
6. Click **Attach** on any row → file downloaded and added to `invoice_attachment_ids`.

### Python Dependencies
Requires `google-api-python-client` and `google-auth` in the Odoo virtualenv.
Install: `pip install google-api-python-client google-auth`

## Accounting Injection (v1.38.0)

### Overview
Bridges `revolut.transaction` → Odoo accounting by creating `account.bank.statement.line` records from synced transactions. This enables Revolut transactions to appear in Odoo's bank reconciliation widget.

### New Model

**`revolut.account.journal.map`** (`models/revolut_account_journal_map.py`)
- Maps Revolut accounts (by UUID) to Odoo bank journals.
- Core fields: `revolut_account_id`, `revolut_account_name`, `journal_id` (Many2one → account.journal), `currency_id`, `last_sync_balance`, `odoo_balance` (computed).
- Extended Revolut fields (v1.40.0): `revolut_account_state` (active/inactive), `revolut_public`, `revolut_created_at`, `revolut_updated_at`.
- Bank detail fields: `iban`, `bic`, `sort_code`, `account_no`, `routing_number`, `beneficiary`, `bank_country` — extracted from the first `bank_details` array element in the API response.
- `raw_json` (Text): stores the full API response for each account.
- `action_verify_balance()`: fetches current Revolut balance via API, compares with sum of posted statement lines in the linked journal.
- `action_sync_transactions()`: syncs Revolut transactions for this specific account only (paginated, same logic as the global sync but scoped to one account).

### Revolut Transaction Changes

New fields on `revolut.transaction`:
- `statement_line_id` (Many2one → account.bank.statement.line): links a transaction to its injected statement line.
- `is_injected` (Boolean, computed/stored): True when `statement_line_id` is set.

New methods:
- `action_inject_to_accounting()`: creates `account.bank.statement.line` records for selected completed transactions. Uses `online_transaction_identifier` for deduplication. Best-effort partner matching via merchant name or counterparty IBAN.
- `action_remove_from_accounting()`: unreconciles (if needed) and deletes the linked statement line + journal entry. Clears the link.
- `_find_partner_for_transaction()`: searches `res.partner` by merchant name, then `res.partner.bank` by counterparty account.

### Config Changes

New field on `legacy.accounting.config`:
- `account_mapping_ids`: computed One2many showing all `revolut.account.journal.map` records for the company.

New method:
- `action_fetch_revolut_accounts()`: calls GET /accounts on Revolut API, creates/updates mapping records.

### UX Flow
1. Configuration → Revolut Business API Integration → Step 7 → **Fetch Revolut Accounts**.
2. Link each Revolut account to an Odoo bank journal.
3. Go to Expenses Matching → select completed transactions → Actions menu → **Inject to Accounting**.
4. Open Odoo Accounting → Bank Reconciliation → transactions appear.
5. To undo: select transactions → Actions menu → **Remove from Accounting**.
6. Verify balance: Configuration → Revolut Account Mappings → click **Verify** on a mapping row.

### Internal Transfer Handling (v1.48.0)

When injecting internal transfers (`transfer_between_accounts=True`), the system uses the company's **transfer account** (`res.company.transfer_account_id`) as the counterpart instead of the journal's suspense account. This ensures transfers appear as balance movements between bank journals — not as P&L income/expense items.

- **Counterpart account**: `company.transfer_account_id` (a reconcilable Current Assets intermediary) is passed via `counterpart_account_id` in the statement line vals. Odoo's `account.bank.statement.line.create()` natively supports this (line 372 of source).
- **Partner**: Set to the company's own partner (`company.partner_id`) — Odoo convention for internal transfers.
- **Payment reference**: Descriptive format: `"Internal transfer from/to {other_account_name}"`.
- **Both sides**: When both legs of a transfer are injected (one per journal), the transfer account entries can be reconciled in Odoo's reconciliation widget, closing the loop.
- **FCF one-sided transfers**: For CSV-imported FCF transactions where only one side exists, the transfer account counterpart still correctly avoids P&L impact. The other side appears as an API-synced transaction on the Revolut account.

### Timezone-Aware Settlement Dates (v1.49.0)

Revolut API provides all timestamps in UTC. The module supports timezone conversion for accurate local-date accounting:

- **`settlement_date`** (stored, Date): `completed_at.date()` falling back to `created_at.date()`, in UTC. Used for sorting and grouping.
- **`settlement_date_local`** (computed, Date): Same datetime converted to the configured accounting timezone. This is the date used when injecting into Odoo accounting.
- **`accounting_timezone`** (on `legacy.accounting.config`): Selectable timezone (e.g. `Europe/Vilnius`). Found in Configuration → Timezone section.
- **Why it matters**: A transaction completed at 23:30 UTC on Jan 15 is actually Jan 16 in `Europe/Vilnius` (UTC+2). The local date is the correct accounting date.

### Revolut TX Ref — Synthetic Unique ID (v1.51.0)

Each `revolut.transaction` gets a computed `revolut_tx_ref` = `{revolut_id}_{account_revolut_id}`. This is unique per account-side, solving the problem where currency conversions create two transactions with the same `revolut_id` on different accounts.

- **`revolut_tx_ref`** (Char, computed/stored, trigram-indexed) on `revolut.transaction`: `{revolut_id}_{account_revolut_id}`.
- **`revolut_tx_ref`** (Char, trigram-indexed) on `account.bank.statement.line`: copied from the transaction during `action_inject_to_accounting()`.
- **`revolut_tx_ref`** (related, stored) on `account.move.line`: reads from `move_id.statement_line_id.revolut_tx_ref`.
- **Dedup check**: uses `revolut_tx_ref` instead of `revolut_id`, so each side of a conversion gets its own statement line.
- **View**: inherited `account.move.line` tree adds an optional "Revolut TX ID" column (hidden by default).
- **Model file**: `models/account_bank_statement_line.py`.

### Key Design Decisions
- Statement lines only (not full statements) — Odoo 17 pattern.
- `online_transaction_identifier` used as dedup key (same pattern as Odoo online sync).
- Only `completed` transactions are injected.
- Injection is a separate deliberate action — never auto-injected on sync.
- Reversible: remove action unreconciles + deletes the statement line and its journal entry.

## Flexible Cash Funds (FCF) CSV Import (v1.44.0)

Revolut "Flexible Cash Funds" (money market fund accounts like save.usd, save.eur) are not available via the Revolut API. Users download CSV statements from the Revolut dashboard and import them into Odoo.

### How it works

1. **Manual account mapping**: Go to Configuration → Revolut Account Mappings → Create. Enter a name (e.g. "save.usd"), select currency, assign a bank journal. The record is flagged `is_manual=True` and gets an auto-generated UUID as `revolut_account_id`.
2. **CSV import**: On the manual account form, click "Import FCF CSV" to open the wizard (`fcf.csv.import.wizard`). Upload the CSV downloaded from Revolut.
3. **Transaction creation**: The wizard parses each CSV row and creates `revolut.transaction` records with state=completed and FCF-specific transaction types (`fcf_buy`, `fcf_sell`, `fcf_interest`, `fcf_fee`).
4. **Deduplication**: A deterministic `revolut_id` is generated from `md5(date|description|value)` — re-importing the same CSV is safe.
5. **Accounting injection**: Use the standard "Inject to Accounting" flow on the created transactions.

### CSV format

```
Date (UTC), Description, Value, Price per share, Quantity of shares
"Jan 2, 2025", "BUY USD Class R IE000ZEZXAJ7", "$500.00", ...
```

### New transaction types

- `fcf_buy` — fund purchase (BUY)
- `fcf_sell` — fund redemption (SELL)
- `fcf_interest` — interest (PAID, Reinvested, WITHDRAWN)
- `fcf_fee` — service fee (Service Fee Charged)

### Dedicated FCF Menu & UX (v1.45.0)

- **Menu**: Top-level "Flexible Cash Funds" menu item (sequence 30) under the Revolut root menu, visible to the accountant group.
- **Tree view**: Shows Account Name, Currency, Linked Revolut Account, Transaction count, Odoo Balance — only manual (`is_manual=True`) accounts.
- **Form view**: Clean workspace with smart button ("X Transactions"), "Import FCF CSV" header button, account details and balance. No Revolut API sections, no journal assignment (done via Configuration → Account Mappings).
- **Smart button**: Opens `revolut.transaction` filtered to this account's FCF types (`fcf_buy`, `fcf_sell`, `fcf_interest`, `fcf_fee`).
- **Computed field**: `fcf_transaction_count` counts FCF-type transactions for the account.

### Account Linking & Transfer Logic (v1.47.0)

- **`account_map_id`** (Many2one on `revolut.transaction`): Links transactions to their `revolut.account.journal.map` record. Set during API sync and CSV import. Renaming an account automatically reflects in transactions.
- **`transfer_other_account_map_id`** (Many2one on `revolut.transaction`): Links the "other side" of internal transfers to an account map record.
- **`source`** (Selection on `revolut.transaction`): `'api'` for API-synced, `'csv'` for CSV-imported. Shown as badge in tree/form views.
- **Opportunistic linking**: During API sync, `_upsert_transaction` searches `revolut.account.journal.map` by the leg's `account_id` to set Many2one links. When a user creates an FCF account with the correct Revolut account ID (the one Revolut uses internally in legs), API-synced transfers involving that FCF account are automatically linked.
- **FCF buy/sell**: Marked as `transfer_between_accounts=True` during CSV import. The counterpart account is resolved automatically when the API-synced side of the transfer has legs referencing the FCF account ID.
- **Migration**: `post-migrate.py` backfills `account_map_id`, `transfer_other_account_map_id`, and `source` for all existing transactions.

### Models

- `fcf.csv.import.wizard` (TransientModel) — CSV upload and parsing
- `revolut.account.journal.map` — extended with `is_manual`, `fcf_transaction_count`

## Vendor Bill Creation (v1.52.0)

### Overview
Creates Odoo vendor bills (`account.move`, `move_type='in_invoice'`) from PDF/image attachments on Revolut transactions. Leverages `jito_invoice_extract_ai` for AI-powered data extraction.

### Flow
1. User attaches invoice PDF to a Revolut transaction (via Revolut API, Gmail, or manual upload)
2. User clicks **Create Vendor Bill** (form) or selects batch action **Create Vendor Bills** (tree)
3. System creates a draft vendor bill, copies the best PDF attachment, and triggers AI extraction
4. AI extracts: vendor name/VAT, invoice date, reference, currency, line items, taxes
5. **Auto-post**: if all key fields are populated and bill amount matches TX amount (±5%), bill is auto-posted
6. **Auto-reconcile**: if TX is already injected to accounting and bill is posted, the payable line is reconciled with the statement line

### Key Files
- `models/revolut_bill_creation.py` — `_inherit = 'revolut.transaction'`, bill creation + confidence check + reconciliation
- `models/account_move_revolut.py` — `revolut_transaction_id` reverse link on `account.move`

### Fields on `revolut.transaction`
- `vendor_bill_id` (Many2one → account.move): link to created vendor bill
- `has_vendor_bill` (Boolean, computed/stored): True when linked

### Fields on `account.move`
- `revolut_transaction_id` (Many2one → revolut.transaction): reverse traceability link

### Confidence Criteria for Auto-Post
All must be true: `partner_id` set, `invoice_line_ids` exist, `invoice_date` set, `ai_extract_state == 'done'`, bill total within 5% of TX amount.

## Key Patterns & Constraints

- Requires `openssl` to be installed on the server (standard on all Linux distros).
- The `private_cert_pem` field is stored in the database (plain text). Treat this record with appropriate access controls.
- Copy-to-clipboard uses Odoo's built-in `CopyClipboardText` widget (no custom JS required).
- Access control: `base.group_user` has full read/write/create access; no delete.
- Menu entry: **Revolut Business API Integration → Revolut Business API Configuration**.
- The `action_open_config()` method is decorated with `@api.model` and is called by the server action in `menus.xml`.

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

## Key Patterns & Constraints

- Requires `openssl` to be installed on the server (standard on all Linux distros).
- The `private_cert_pem` field is stored in the database (plain text). Treat this record with appropriate access controls.
- Copy-to-clipboard uses Odoo's built-in `CopyClipboardText` widget (no custom JS required).
- Access control: `base.group_user` has full read/write/create access; no delete.
- Menu entry: **Revolut Business API Integration → Revolut Business API Configuration**.
- The `action_open_config()` method is decorated with `@api.model` and is called by the server action in `menus.xml`.

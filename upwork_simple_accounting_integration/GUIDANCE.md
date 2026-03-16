# Upwork Simple Accounting — Module Guidance

## What This Module Does

Integrates Upwork with Odoo via OAuth2 to:
1. Authenticate with Upwork using Authorization Code Grant
2. Select an Upwork organization and auto-detect the accounting entity ID
3. Download the full transaction ledger (transactionHistory GraphQL query)
4. Display all transaction fields in a rich detail viewer
5. Generate DOCX/PDF invoices from transaction data using Jinja2 templates

> **Important:** This module does NOT use the Odoo `account` module. It is a standalone data viewer and document generator only.

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
2. The `callback_url` is auto-set to `{base_url}/upwork/callback`
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

## Important Patterns

- Singleton pattern: `lock_field = Char(default='global')` + `UNIQUE(lock_field)` SQL constraint
- Token refresh: automatic via `_refresh_access_token()` when token is within 1 minute of expiry
- Transaction upsert: search by `record_id` → write if exists, create if not
- Dates from API: ISO8601 with offset `+0000` normalized to UTC before storage

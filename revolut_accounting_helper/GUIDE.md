# Revolut Accounting Helper – Module Guide

## What this module does
Provides a Google Account Manager and a Google Drive file-upload wizard for
Revolut-related accounting workflows. Users connect their own Google account
**inside Odoo** (without affecting their Odoo login) and can then upload files
directly to a specified Google Drive folder.

---

## Google Account Manager

### Purpose
Allows each Odoo user to connect / disconnect a personal Google account without
touching their Odoo session.  Accessible via
**Revolut accounting helper → Account Manager**.

### UX Flow
```
Account Manager
├── Not connected
│     ├── "Connect Google Account" → opens Google consent in new tab
│     │       └── After authorising: tab closes, user clicks "Refresh Status"
│     └── Page reloads → now shows "Connected as user@gmail.com"
└── Connected
      ├── "Log Out"        → clears tokens + email, page reloads (disconnected)
      └── "Switch Account" → opens Google consent again to re-authorise
```

---

## Google Drive OAuth2 Integration

### Architecture

```
Admin → Settings → enter Client ID / Secret → ir.config_parameter
User  → Account Manager → "Connect Google Account"
      → Google consent screen (Drive + email scopes)
      → /google/drive/callback → stores tokens + email in google.drive.credentials
User  → "Refresh Status" → Account Manager shows email
User  → Google → Drive upload → fill folder URL + pick file → "Upload" → Drive API v3
```

### Models

| Model | File | Purpose |
|-------|------|---------|
| `google.drive.credentials` | `models/google_drive_credentials.py` | Per-user OAuth2 tokens (access + refresh + email), auto-refresh logic |
| `google.account.manager` | `models/google_account_manager.py` | TransientModel powering the Account Manager UI (connect / disconnect) |
| `res.users` (inherited) | `models/res_users.py` | Adds `google_drive_account_id` Many2one to credentials |
| `res.config.settings` (inherited) | `models/res_config_settings.py` | Exposes `google_drive_client_id` / `google_drive_client_secret` settings |
| `google.drive.upload.wizard` | `wizards/google_drive_upload_wizard.py` | Transient wizard: connect / upload / show result |

### Controllers

| Route | File | Purpose |
|-------|------|---------|
| `GET /google/drive/callback` | `controllers/google_drive_auth.py` | Exchanges auth code for tokens, fetches Google email, stores them, shows success page |

### Views

| File | Purpose |
|------|---------|
| `views/menus.xml` | Main menu + Account Manager form + Drive Upload / Gmail search actions |
| `views/google_drive_upload.xml` | Drive Upload wizard form (three states: not_connected / draft / done) |
| `views/res_config_settings_views.xml` | Settings section for OAuth credentials |

---

## Configuration (Admin)

1. In Google Cloud Console: create an OAuth 2.0 client (Web application type).
   Add `{your_odoo_base_url}/google/drive/callback` as an Authorised redirect URI.
2. In Odoo → Settings → **Revolut Helper** section:
   - Enter **Client ID** and **Client Secret**.
3. Save.

## Usage (User)

### Connecting a Google account
1. Open **Revolut accounting helper → Account Manager**.
2. Click **Connect Google Account** → a new browser tab opens with the Google consent screen.
3. Select your Google account and grant access.
4. The success page closes the tab automatically.
5. Back in the Account Manager, click **Refresh Status** → page shows "Connected as …".

### Uploading a file to Drive
1. Open **Revolut accounting helper → Google → Drive upload**.
2. If not connected: follow the *Connecting* steps first (or use the wizard's own Connect button).
3. Paste a Google Drive folder URL, pick a file, click **Upload**.
4. On success the *Uploaded* state shows a link to the file in Drive.

### Disconnecting
1. Open **Account Manager**.
2. Click **Log Out** → tokens are cleared, Odoo session is unaffected.

---

---

## Gmail Email Search

### Purpose
Allows users with a connected Google account to search their Gmail inbox directly
from Odoo, view full emails (with HTML rendering), and download attachments on demand.
Accessible via **Revolut accounting helper → Google → Gmail Search**.

### UX Flow
```
Gmail Search form
├── Fill search criteria (mixed input OR separate date + keywords)
├── Toggle "With Attachment" and set Max Results
├── Query preview shown live as Gmail query string
├── "Search in Gmail" → calls Gmail API → results loaded
└── Email viewer
      ├── Navigation bar: "← Previous | Email X of N | Next →"
      ├── Email card
      │     ├── Subject header
      │     ├── From / To / CC / Date
      │     ├── Body (HTML or plain-text fallback → snippet fallback)
      │     └── Attachments tree with "Download" button
      └── Bottom navigation bar (mirrors top)
```

### Mixed Input Parsing
The **Quick Search** field accepts free-form text containing a date and keywords
together, e.g. `"10 Jan, 2026 Slack invoice"`. Supported date formats:
- `DD Mon YYYY` / `DD Mon, YYYY` (e.g. `15 Feb 2026`, `15 Feb, 2026`)
- `YYYY-MM-DD` / `YYYY/MM/DD`
- `DD/MM/YYYY`

The date is extracted, populating **Date** and leaving the rest as **Keywords**.

### Models

| Model | File | Purpose |
|-------|------|---------|
| `google.gmail.search.wizard` | `wizards/google_gmail_search_wizard.py` | Main search form; navigation state; related display fields |
| `google.gmail.search.result` | same file | Per-email record: subject, from/to/cc, date, body_html, body_text |
| `google.gmail.search.attachment` | same file | Per-attachment record; on-demand download via Gmail Attachments API |

### Key Fields (wizard)
- `current_result_id` Many2one → active email pointer; updated by prev/next buttons
- `current_attachment_ids` Many2many → attachments of the active email; synced with navigation
- `can_go_prev` / `can_go_next` computed Boolean → drive button visibility
- `current_result_number` / `results_count` → "Email X of N" display

### Attachment Download
Attachment DATA is fetched **on demand** when the user clicks **Download** (not
during search). The method creates a temporary `ir.attachment` and returns a
`/web/content/{id}?download=true` URL.

### Gmail API Scope Required
The `gmail.readonly` scope must be granted. Users who connected their Google
account before this feature was added must **reconnect** via Account Manager.

---

## Important Patterns & Constraints

- **Scopes**: `drive.file` + `userinfo.email` + `gmail.readonly` — `drive.file`
  allows creating files in any folder; `userinfo.email` displays the signed-in
  address; `gmail.readonly` enables read-only Gmail search.
- **Token refresh**: handled transparently in `_get_valid_access_token()`; tokens
  are refreshed when less than 1 minute remains.
- **No `google_account` dependency**: token exchange is done directly with
  `requests` to avoid tight coupling with Enterprise modules.
- **One credential record per user**: enforced by a unique SQL constraint on
  `res.users.google_drive_account_id`.
- **`prompt=consent` + `access_type=offline`**: ensures Google always returns a
  refresh token even on re-authorisation.
- If the refresh token is revoked (400/401 response), stored tokens are cleared
  and the user must reconnect.
- **Google logout ≠ Odoo logout**: calling `action_disconnect_google` only clears
  the stored OAuth tokens; the Odoo session remains active.

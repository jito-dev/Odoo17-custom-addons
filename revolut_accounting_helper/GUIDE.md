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
| `GET /gmail/attachment/download/<id>` | `controllers/google_drive_auth.py` | Fetches Gmail attachment on demand via API and streams it as a file download; verifies wizard ownership before serving |

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
└── Results (all emails rendered inline, scrollable)
      ├── Summary bar: "Found N email(s)"
      └── Gmail-style email cards (one per result, no clicking required)
            ├── HEADER (gray): avatar circle + From: / Subject: / Date:
            ├── BODY (white): rendered HTML email, max-height 500px scrollable
            ├── ATTACHMENTS (blue bg, if any): file chips with ↓ Download links
            │     → actual file download via GET /gmail/attachment/download/<id>
            └── RELEVANT LINKS (green bg, if any): keyword-matched clickable chips
                (invoice / receipt / payment / download / pdf / stripe / revolut / etc.)
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
- `result_ids` One2many → stores all search results
- `results_html` Html (computed, store=False, sanitize=False) → generated Gmail-style card HTML; all emails rendered inline on page
- `results_count` Integer → conditional display of results section
- `search_performed` Boolean → controls "no results" alert visibility

### Key Fields (result)
- `attachment_count` Integer (computed, stored) → used in `results_html` for attachment row

### Module-level helpers (wizard file)
- `_prepare_email_html(html)` → strips `<script>`, `<style>`, `<html>/<head>/<body>` wrappers; returns body content for inline rendering
- `_extract_keyword_links(html)` → regex-parses `<a href>` tags, returns up to 5 (url, label) matching `_LINK_KEYWORDS`
- `_extract_sender_name(sender)` → extracts display name from "Name \<email>" format
- `_LINK_KEYWORDS` → frozenset covering financial terms (invoice, receipt, payment, stripe, revolut, etc.) **and** collaboration/communication services (github, gitlab, slack, teams, discord, meet, zoom, webex, notion, jira, drive, docs, sheets, dropbox, loom, figma, trello, asana, linear, clickup, …)
- `_extract_keyword_links` regex handles double-quoted, single-quoted, and unquoted `href` attribute values

### Attachment Download (controller)
Attachment data is fetched **on demand** — nothing is ever saved to the Odoo
database or `ir.attachment`. Both the HTML card chip links and the
`action_download` method route to the same controller:
`GET /gmail/attachment/download/<attachment_id>`. The controller fetches the
binary from the Gmail API and streams it directly to the browser.
Filenames are encoded using **RFC 5987** (`filename*=UTF-8''<percent-encoded>`)
so non-ASCII characters (e.g. Cyrillic, accented letters) do not cause
`UnicodeEncodeError` in the HTTP response header.

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

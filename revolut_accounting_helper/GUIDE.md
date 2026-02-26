# Revolut Accounting Helper – Module Guide

## What this module does
Provides a Google Drive file-upload wizard for Revolut-related accounting workflows.
Users can upload files directly to a specified Google Drive folder from within Odoo.

---

## Google Drive OAuth2 Integration

### Architecture

```
Admin → Settings → enter Client ID / Secret → ir.config_parameter
User  → Upload wizard (state: not_connected) → "Connect Google Drive"
      → /google/drive/auth → Google consent screen
      → /google/drive/callback → stores tokens in google.drive.credentials
User  → "Refresh Status" → state becomes 'draft'
User  → fill folder URL + pick file → "Upload" → Drive API v3
```

### Models

| Model | File | Purpose |
|-------|------|---------|
| `google.drive.credentials` | `models/google_drive_credentials.py` | Per-user OAuth2 tokens (access + refresh), auto-refresh logic |
| `res.users` (inherited) | `models/res_users.py` | Adds `google_drive_account_id` Many2one to credentials |
| `res.config.settings` (inherited) | `models/res_config_settings.py` | Exposes `google_drive_client_id` / `google_drive_client_secret` settings |
| `google.drive.upload.wizard` | `wizards/google_drive_upload_wizard.py` | Transient wizard: connect / upload / show result |

### Controllers

| Route | File | Purpose |
|-------|------|---------|
| `GET /google/drive/auth` | `controllers/google_drive_auth.py` | Redirects to Google consent screen |
| `GET /google/drive/callback` | `controllers/google_drive_auth.py` | Exchanges auth code for tokens, stores them, shows success page |

### Views

| File | Purpose |
|------|---------|
| `views/google_drive_upload.xml` | Wizard form (three states: not_connected / draft / done) |
| `views/res_config_settings_views.xml` | Settings section for OAuth credentials |
| `views/menus.xml` | Main menu + Drive Upload action |

---

## Configuration (Admin)

1. In Google Cloud Console: create an OAuth 2.0 client (Web application type).
   Add `{your_odoo_base_url}/google/drive/callback` as an Authorised redirect URI.
2. In Odoo → Settings → **Revolut Helper** section:
   - Enter **Client ID** and **Client Secret**.
3. Save.

## Usage (User)

1. Open **Revolut accounting helper → Google → Drive upload**.
2. If state is *Not Connected*: click **Connect Google Drive** → a new browser tab opens.
3. Authorise access in the Google consent screen → success page auto-closes.
4. Back in wizard, click **Refresh Status** → state becomes *Ready*.
5. Paste a Google Drive folder URL, pick a file, click **Upload**.
6. On success the *Uploaded* state shows a link to the file in Drive.

---

## Important Patterns & Constraints

- **Scope**: `https://www.googleapis.com/auth/drive.file` — minimal, allows creating files in any folder.
- **Token refresh**: handled transparently in `_get_valid_access_token()`; tokens are refreshed when less than 1 minute remains.
- **No `google_account` dependency**: token exchange is done directly with `requests` to avoid tight coupling with Enterprise modules.
- **One credential record per user**: enforced by a unique SQL constraint on `res.users.google_drive_account_id`.
- **`prompt=consent` + `access_type=offline`**: ensures Google always returns a refresh token.
- If the refresh token is revoked (400/401 response), stored tokens are cleared and the user must reconnect.

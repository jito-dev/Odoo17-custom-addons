# Secrets Manager — Developer Guide

## Purpose

A secure, encrypted vault for storing and sharing sensitive credentials within Odoo.
All data is encrypted at rest using AES-256 (Fernet). The encryption key exists only
in server memory — an Odoo restart automatically seals the vault.

---

## Architecture: Seal / Unseal

**Module-level variable** (`models/secret_vault.py`):

```python
_VAULT_KEY: Optional[bytes] = None  # None = sealed
```

- On **server start**: `_VAULT_KEY = None` → vault is sealed
- Admin enters master passphrase → PBKDF2-SHA256 (480,000 rounds) derives a Fernet key → stored in `_VAULT_KEY`
- **Salt** (random 32 bytes) is stored in `ir.config_parameter` (non-sensitive; only needed for key derivation)
- **Passphrase verifier** (separate PBKDF2 hash) stored in `ir.config_parameter` for validation; the passphrase itself is never stored
- All encrypt/decrypt operations check `_VAULT_KEY is not None` first

---

## Models

### `secret.vault` (`models/secret_vault.py`)
Singleton. Manages seal/unseal state and exposes `encrypt()` / `decrypt()` service methods.

| Method | Description |
|--------|-------------|
| `initialize(passphrase)` | First-time setup: generates salt, stores verifier, unseals |
| `unseal(passphrase)` | Validates passphrase, sets `_VAULT_KEY` in memory |
| `seal()` | Clears `_VAULT_KEY` |
| `rekey(current, new)` | Re-encrypts all secrets under a new passphrase (admin only) |
| `encrypt(plaintext)` | Fernet-encrypts; raises `UserError` if sealed |
| `decrypt(ciphertext)` | Fernet-decrypts; raises `UserError` if sealed |
| `get_state()` | Returns `{is_initialized, is_unsealed}` for client use |

### `secret.entry` (`models/secret_entry.py`)
Main secrets model. `encrypted_payload` stores Fernet-encrypted JSON.

**Payload JSON format:**
```json
{
  "type": "login",
  "fields": [
    {"key": "username", "label": "Username", "value": "...", "sensitive": false},
    {"key": "password", "label": "Password", "value": "...", "sensitive": true}
  ],
  "custom_fields": [
    {"label": "2FA Seed", "value": "...", "sensitive": true}
  ]
}
```

**Save flow:**
1. Owl widget serialises payload → writes JSON to non-stored `transient_payload` field
2. Form save triggers `create()` / `write()`
3. Model detects `transient_payload` → encrypts → writes to `encrypted_payload`
4. `transient_payload` is never persisted (non-stored field)

**Reveal flow:**
1. Widget calls `get_decrypted_payload()` RPC → server decrypts → returns plaintext dict
2. Audit log entry created for 'reveal'
3. Values held in Owl component state only

### `secret.tag` (`models/secret_tag.py`)
Simple tags with color index (Odoo pattern).

### `secret.share` (`models/secret_share.py`)
Records who a secret is shared with and when it expires.
- Unique constraint: one share record per (secret, user) pair
- `is_expired` computed from `expires_at < now()`

### `secret.audit.log` (`models/secret_audit_log.py`)
Append-only audit trail. ACL grants no write/create/unlink to anyone — only `sudo()` in model code can write entries.

---

## Security Model

### Groups
- `group_secrets_admin` — Full access: all secrets, vault, audit log
- `group_secrets_user` — Own secrets + shared-with-them

### Record Rules
- `secret.entry`: users see `user_id = current` OR `share_ids where user = current AND not expired`
- `secret.entry`: admins see all
- `secret.audit.log`: users see own entries; admins see all

---

## Frontend: `SecretListView` (custom `js_class`)

Registered as view type `secret_list` in the views registry.

**Used on:** `view_secret_entry_tree` (My Secrets, All Secrets tree views).

**Key behaviours:**
- Extends `listView` with a custom `SecretListController`
- Adds a "New Secret" primary button in the control panel (only visible when `activeActions.create` is true)
- Clicking "New Secret" opens a blank `secret.entry` form via `actionService.doAction`
- Button template: `jito_secrets_manager.SecretListView.Buttons` (inherits `web.ListView.Buttons`)

**Files:** `static/src/js/secret_list_view.js`, `static/src/xml/secret_list_view.xml`

---

## Frontend: `SecretPayloadWidget` (Owl)

Registered as field widget `SecretPayloadWidget` for `text` fields.

**Used on:** `transient_payload` field in the secret entry form.

**Key behaviours:**
- Loads decrypted payload via `get_decrypted_payload()` on render
- Edit mode: writes JSON to `transient_payload` via `record.update()` on each change
- Reveal: toggles field visibility in state (data already loaded from server)
- Copy: uses `navigator.clipboard.writeText()` — never reveals value on screen
- `+ Add Field`: appends `{label, value, sensitive}` to `custom_fields` array

---

## Menus

| Menu | Role | Action |
|------|------|--------|
| My Secrets | User | `action_my_secrets` (domain: owner = me) |
| Shared with Me | User | `action_shared_with_me` (domain: active share) |
| All Secrets | Admin | `action_all_secrets` (no domain) |
| Configuration → Vault | Admin | Seal/Unseal form |
| Configuration → Tags | Admin | Tag management |
| Configuration → Audit Log | Admin | Full audit trail |

---

## Constraints & Important Notes

1. **Never log secret values** — audit log stores only action type, not values
2. **Vault restart seal** — `_VAULT_KEY` is module-level; any server restart clears it
3. **Salt is not secret** — the salt in `ir.config_parameter` is needed only to re-derive the key from the passphrase; it is not sensitive
4. **Single passphrase** — the vault uses one shared admin passphrase; all admins use the same one
5. **Encrypted payload is opaque** — without the key, the `encrypted_payload` column is meaningless ciphertext
6. **Shares are read-only** — sharing grants view access only; shared users cannot edit the secret
7. **Rekey uses direct SQL** — `rekey()` bypasses the ORM `write()` override to avoid creating spurious `edit` audit entries; a single `rekey` audit log entry captures the whole operation

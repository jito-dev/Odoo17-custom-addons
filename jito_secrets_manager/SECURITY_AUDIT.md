# Security Audit Report — Secrets Manager Module
**Module:** `jito_secrets_manager` v17.0.1.12.0
**Audit Date:** 2026-03-17
**Methodology:** Static code review — no automated tests, no code changes
**Scope:** Access control · Encryption & vault · Audit log integrity · Sharing & expiration

---

## Executive Summary

The module demonstrates a **solid security foundation**: the encryption design is sound (Fernet authenticated encryption, PBKDF2-SHA256 key derivation, in-memory-only key, append-only audit log, row-level record rules). No data is plaintext in the database. The vault auto-seals on restart.

However, two **HIGH severity** issues require priority remediation:

1. **Record rule join bug** — An expired share combined with a different user's active share on the same secret bypasses expiry enforcement, granting access to users whose share has lapsed.
2. **Shared-secret write/delete rights** — Users with a shared (read-intent) secret can edit or permanently delete it, violating the principle of least privilege.

**Risk Posture:** Medium-High until HIGH findings are resolved. Post-fix: Low.

| Severity | Count |
|----------|-------|
| CRITICAL | 0 |
| HIGH     | 2 |
| MEDIUM   | 7 |
| LOW/INFO | 5 |

---

## Findings

---

### F-01 · HIGH — Record Rule Join Bug Allows Expiry Bypass

**Domain:** Access Control / Sharing & Expiration
**IDs:** AC-01, SHARE-03

**Description**
The `secret.entry` record rule for users relies on two separate `share_ids` conditions joined with `&`:

```xml
<!-- security/record_rules.xml:22-34 -->
['|',
    ('user_id', '=', user.id),
    '&',
        ('share_ids.shared_with_user_id', '=', user.id),
        ('share_ids.expires_at', '>', time.strftime('%Y-%m-%d %H:%M:%S'))
]
```

In Odoo's domain engine, each `share_ids.*` condition generates a **separate SQL subquery**:

```sql
-- Condition 1
secret_entry.id IN (SELECT secret_id FROM secret_share WHERE shared_with_user_id = $uid)
-- Condition 2
secret_entry.id IN (SELECT secret_id FROM secret_share WHERE expires_at > $now)
```

These subqueries are ANDed — they do **not** require the same `secret_share` row to satisfy both. Consider:

| Share | `shared_with_user_id` | `expires_at`      |
|-------|-----------------------|-------------------|
| S1    | User A                | Yesterday (expired) |
| S2    | User B                | Tomorrow (active)  |

For **User A**:
- Condition 1 → True (S1 matches `shared_with = User A`)
- Condition 2 → True (S2 matches `expires_at > now`, different row)
- Combined → **True** → User A retains access despite their share being expired

**Evidence:** `security/record_rules.xml:22-34`

**Recommendation**
Use `_compute_is_shared_with_me` as an additional server-side guard, or rewrite the domain to use a stored computed Boolean field `is_actively_shared_with_me` that correctly evaluates whether a single share row satisfies both conditions simultaneously. Example approach:

```python
# models/secret_entry.py — add stored computed field
is_actively_shared_with_me = fields.Boolean(compute='_compute_sharing', store=True)

@api.depends('share_ids.shared_with_user_id', 'share_ids.expires_at')
def _compute_sharing(self):
    now = fields.Datetime.now()
    for rec in self:
        rec.is_actively_shared_with_me = any(
            s.shared_with_user_id.id == self.env.uid and
            s.expires_at and s.expires_at > now
            for s in rec.share_ids
        )
```

Then record rule: `('is_actively_shared_with_me', '=', True)`. Note this requires the field to be stored and recomputed on share changes.

---

### F-02 · HIGH — Shared-Secret Recipients Have Full Write/Delete Rights

**Domain:** Access Control / Sharing & Expiration
**IDs:** AC-08, SHARE-07

**Description**
The user record rule grants `perm_read`, `perm_write`, `perm_create`, and `perm_unlink` to secrets that are "owned by me or shared with me" — making no distinction between ownership and sharing:

```xml
<!-- security/record_rules.xml:29-34 -->
<field name="perm_read"   eval="True"/>
<field name="perm_write"  eval="True"/>
<field name="perm_create" eval="True"/>
<field name="perm_unlink" eval="True"/>
```

A user who receives a share of someone else's secret can:
- Edit the secret name, type, tags, and all payload fields
- **Permanently delete the secret** (the owner loses their own credential)

This violates the principle of least privilege. Sharing should convey read (and possibly copy) access, not write/delete.

**Evidence:** `security/record_rules.xml:29-34`, `security/ir.model.access.csv:4`

**Recommendation**
Split into two rules: one for **own** secrets (read/write/create/unlink) and one for **shared** secrets (read-only). Example:

```xml
<!-- Rule: own secrets — full access -->
<record id="rule_secret_entry_user_own" ...>
    <field name="domain_force">[('user_id', '=', user.id)]</field>
    <field name="perm_read" eval="True"/>
    <field name="perm_write" eval="True"/>
    <field name="perm_create" eval="True"/>
    <field name="perm_unlink" eval="True"/>
</record>

<!-- Rule: shared secrets — read only -->
<record id="rule_secret_entry_user_shared" ...>
    <field name="domain_force">
        ['&', ('share_ids.shared_with_user_id', '=', user.id),
               ('share_ids.expires_at', '>', time.strftime('%Y-%m-%d %H:%M:%S'))]
    </field>
    <field name="perm_read"   eval="True"/>
    <field name="perm_write"  eval="False"/>
    <field name="perm_create" eval="False"/>
    <field name="perm_unlink" eval="False"/>
</record>
```

---

### F-03 · MEDIUM — Passphrase Length Not Enforced at Model Layer

**Domain:** Encryption & Vault
**ID:** ENC-07

**Description**
The 12-character minimum passphrase requirement is enforced only in `UnsealWizard.action_confirm()`:

```python
# wizards/unseal_wizard.py:34-35
if len(self.passphrase) < 12:
    raise UserError(_('Passphrase must be at least 12 characters long.'))
```

It is **not** enforced in `SecretVault.initialize()` or `SecretVault.unseal()`. An administrator who calls `secret.vault.initialize('abc')` directly via RPC (bypassing the wizard) can set a short, weak passphrase without any rejection.

**Evidence:** `models/secret_vault.py:121-142`, `wizards/unseal_wizard.py:34-35`

**Recommendation**
Move passphrase length validation into `SecretVault.initialize()` and optionally add complexity rules:

```python
# models/secret_vault.py — inside initialize()
if len(passphrase) < 12:
    raise UserError(_('Passphrase must be at least 12 characters.'))
```

---

### F-04 · MEDIUM — Failed Unseal Attempts Are Not Logged

**Domain:** Audit Log Integrity
**ID:** AUDIT-05

**Description**
When an incorrect passphrase is provided during unseal, the vault simply raises a `UserError` and returns:

```python
# models/secret_vault.py:109-110
if expected_verifier != verifier:
    raise UserError(_('Incorrect passphrase. The vault remains sealed.'))
```

No audit log entry is created for the failed attempt. This means brute-force or credential-stuffing attacks against the vault passphrase leave no trace in the audit trail.

**Evidence:** `models/secret_vault.py:109-110`

**Recommendation**
Log failed attempts before raising the exception:

```python
# Before raise:
self.env['secret.audit.log'].sudo()._log(secret=None, action='unseal_failed')
```

Add `'unseal_failed'` to the `action` selection field in `secret_audit_log.py`. Additionally, consider rate limiting (e.g., a short delay or lockout after N failures).

---

### F-05 · MEDIUM — Share Revocation (Deletion) Is Not Logged

**Domain:** Audit Log Integrity
**ID:** AUDIT-04

**Description**
`SecretShare.create()` logs a `'share'` event, but there is no `unlink()` override in `secret.share`. Revoking a share (deleting the share record) leaves no audit trail:

```python
# models/secret_share.py — no unlink() override
```

An administrator or secret owner can silently revoke access without any record in the audit log.

**Evidence:** `models/secret_share.py` (entire file — no `unlink`)

**Recommendation**
Add an `unlink()` override:

```python
def unlink(self):
    for rec in self:
        self.env['secret.audit.log'].sudo()._log(rec.secret_id, 'unshare')
    return super().unlink()
```

Add `'unshare'` to the `action` selection in `secret_audit_log.py`.

---

### F-06 · MEDIUM — No Explicit Ownership Check When Creating a Share

**Domain:** Access Control / Sharing & Expiration
**IDs:** AC-09, SHARE-04

**Description**
`secret.share` ACL grants `perm_create=1` to all users. The `create()` method contains no explicit check that the caller owns (or is an admin of) the secret being shared:

```python
# models/secret_share.py:63-68
@api.model_create_multi
def create(self, vals_list):
    records = super().create(vals_list)
    for rec in records:
        self.env['secret.audit.log'].sudo()._log(rec.secret_id, 'share')
    return records
```

Protection against sharing someone else's secret relies on Odoo's implicit Many2one access check (if User A can't read the secret, they can't set `secret_id` to it). This is an indirect, implicit guard — not a documented invariant of the `secret.share` model.

**Evidence:** `models/secret_share.py:63-68`, `security/ir.model.access.csv:7`

**Recommendation**
Add an explicit constraint:

```python
@api.constrains('secret_id')
def _check_share_ownership(self):
    for rec in self:
        if not self.env.user.has_group('jito_secrets_manager.group_secrets_admin'):
            if rec.secret_id.user_id.id != self.env.uid:
                raise ValidationError(_('You can only share secrets you own.'))
```

---

### F-07 · MEDIUM — Vault Key Unavailable in Other Worker Processes

**Domain:** Encryption & Vault
**ID:** ENC-09

**Description**
`_VAULT_KEY` is a module-level Python variable. In a multi-worker Odoo deployment (Gunicorn), each worker process has its own memory space. Unsealing via one worker sets `_VAULT_KEY` only in that worker — other workers remain sealed.

Additionally, the key cannot be explicitly zeroed after use (Python strings are immutable and memory-managed by the GC). During the vault's unsealed lifetime, the key persists in any worker's heap until GC collects the old reference.

**Evidence:** `models/secret_vault.py:17`

**Recommendation**
Document this limitation clearly for operators: after unsealing, users may encounter "vault sealed" errors intermittently if requests land on different workers. Operators should be aware that unsealing must happen once per restart, and all workers will eventually serve vault operations once they receive an unseal request (if using sticky sessions) or by using a shared cache (Redis/Memcached) to distribute the key — though the latter has its own security implications.

---

### F-08 · MEDIUM — No Key Rotation Mechanism

**Domain:** Encryption & Vault
**ID:** ENC-10

**Description**
The vault provides no mechanism to rotate the encryption key. If the master passphrase is compromised, there is no supported path to re-encrypt all secrets under a new passphrase without:
1. Decrypting all secrets while unsealed
2. Changing the passphrase (re-derive key)
3. Re-encrypting all secrets with the new key

No tooling or documented procedure exists for this operation.

**Evidence:** `models/secret_vault.py` (no rotation method), `wizards/unseal_wizard.py` (only init/unseal)

**Recommendation**
Implement a `rotate_passphrase(old_passphrase, new_passphrase)` model method that:
1. Verifies old passphrase
2. Decrypts all `secret.entry` records
3. Derives new key from new passphrase
4. Re-encrypts all records
5. Updates the salt + verifier
6. Logs the rotation event

---

### F-09 · LOW — Vault UI Incorrectly Claims AES-256

**Domain:** Encryption & Vault
**ID:** ENC-02

**Description**
The vault form view displays:

```xml
<!-- views/secret_vault_views.xml:53-55 -->
The vault uses AES-256 (Fernet) encryption with a PBKDF2-derived key.
```

This is inaccurate. Fernet (Python `cryptography` library) uses **AES-128-CBC** + **HMAC-SHA256**. The 32-byte PBKDF2 output is split as 16 bytes for HMAC and 16 bytes for AES — making the AES key 128-bit, not 256-bit.

AES-128 is not a vulnerability (no practical attacks exist), but the documentation misrepresents the actual cipher strength.

**Evidence:** `views/secret_vault_views.xml:53-55`, Python `cryptography` Fernet spec

**Recommendation**
Update the UI text to: `"AES-128-CBC + HMAC-SHA256 (Fernet) with PBKDF2-derived key"`.

---

### F-10 · LOW — PBKDF2 Iteration Count Below 2023 OWASP Recommendation

**Domain:** Encryption & Vault
**ID:** ENC-01

**Description**
The vault uses 480,000 PBKDF2-SHA256 iterations:

```python
# models/secret_vault.py:21
_ITERATIONS = 480_000
```

OWASP's 2023 Password Storage Cheat Sheet recommends **600,000** iterations for PBKDF2-HMAC-SHA256. The current count (480k) is below this guidance, though it remains substantially above the 2021 recommendation of 310,000 and is not practically exploitable.

**Evidence:** `models/secret_vault.py:21`

**Recommendation**
Increase to 600,000 iterations for alignment with current OWASP guidance. Note this will require all users to re-unseal the vault after the change (the verifier would need to be recomputed with the new iteration count, which requires a passphrase re-entry).

---

### F-11 · LOW — Non-Constant-Time Verifier Comparison

**Domain:** Encryption & Vault
**ID:** ENC-08

**Description**
The passphrase verifier comparison uses Python's `!=` operator on strings:

```python
# models/secret_vault.py:109
if expected_verifier != verifier:
```

Python's string `!=` is not constant-time, making it theoretically susceptible to timing side-channel attacks. In practice this risk is negligible because:
- The 480k PBKDF2 iterations (~1–2 seconds) dominate timing, dwarfing string comparison
- Network latency jitter makes sub-millisecond timing differences undetectable remotely

**Evidence:** `models/secret_vault.py:109`

**Recommendation**
Use `hmac.compare_digest()` for correctness:
```python
import hmac
if not hmac.compare_digest(expected_verifier, verifier):
```

---

### F-12 · LOW — No Maximum Share Expiration Duration

**Domain:** Sharing & Expiration
**ID:** SHARE-06

**Description**
`expires_at` is required but has no upper bound. A share can be created with `expires_at = datetime(2999, 12, 31)`, making it effectively permanent. This defeats the purpose of time-limited access control.

**Evidence:** `models/secret_share.py:30-34`

**Recommendation**
Add a model-level constraint capping the maximum share duration (e.g., 1 year):

```python
@api.constrains('expires_at')
def _check_expires_at(self):
    max_expiry = fields.Datetime.now() + timedelta(days=365)
    for rec in self:
        if rec.expires_at and rec.expires_at > max_expiry:
            raise ValidationError(_('Share expiration cannot exceed 1 year from today.'))
```

---

### F-13 · INFO — `get_vault_state()` Accessible to All Module Users

**Domain:** Access Control
**ID:** AC-05

**Description**
`get_vault_state()` on `secret.entry` is callable by any user with module access. It returns `{'is_initialized': bool, 'is_unsealed': bool}`. This discloses vault operational state to non-admin users.

**Evidence:** `models/secret_entry.py:207-210`

**Note**
This is intentional — the widget requires vault state to render correctly (sealed placeholder vs. field editor). The information is low-sensitivity (binary state, no key material). No action required unless the deployment requires this information to be admin-only.

---

## Positive Findings

The following security controls are well-implemented:

| # | Control | Evidence |
|---|---------|----------|
| P-01 | **Key never persisted** — only a PBKDF2 verifier is stored; the vault key exists exclusively in memory | `secret_vault.py:17`, `ir.config_parameter` stores only verifier |
| P-02 | **Authenticated encryption** — Fernet (AES-CBC + HMAC-SHA256) prevents ciphertext tampering and forgery | `secret_vault.py:165-166` |
| P-03 | **Verifier derivation path separation** — `salt + b'_verify'` suffix prevents key recovery from a stolen verifier | `secret_vault.py:41` |
| P-04 | **transient_payload never reaches the database** — `create()` and `write()` always pop it before `super()` | `secret_entry.py:158-162`, `169-174` |
| P-05 | **Append-only audit log** — `perm_write=0`, `perm_create=0`, `perm_unlink=0` for all groups; entries only via `sudo()` | `ir.model.access.csv:9-10` |
| P-06 | **Secret name snapshot** — `secret_name` captured at log time; audit entries survive secret deletion (`ondelete='set null'`) | `secret_audit_log.py:61-62`, `13-14` |
| P-07 | **Comprehensive operation logging** — create, reveal, edit, delete, share, seal, unseal all produce audit entries | All model files |
| P-08 | **Auto-seal on restart** — module-level `_VAULT_KEY = None` means every Odoo process restart requires explicit unseal | `secret_vault.py:17` |
| P-09 | **Self-share prevention** — `@api.constrains` raises `ValidationError` if recipient == owner | `secret_share.py:55-61` |
| P-10 | **SQL-level duplicate share prevention** — `unique(secret_id, shared_with_user_id)` constraint race-condition safe | `secret_share.py:41-47` |
| P-11 | **Share expiration required** — `expires_at` is `required=True` at model level | `secret_share.py:30-34` |
| P-12 | **Row-level security** — record rules enforce user ↔ secret isolation for entries, shares, and audit logs | `security/record_rules.xml` |
| P-13 | **Vault operations admin-only** — `secret.vault` ACL has no user-level access; unseal wizard restricted to admin | `ir.model.access.csv:2`, `security_groups.xml` |
| P-14 | **Passphrase match confirmation on init** — wizard validates `passphrase == passphrase_confirm` before initializing | `unseal_wizard.py:32-33` |
| P-15 | **Generic error messages** — wrong passphrase and invalid ciphertext produce non-leaky error messages | `secret_vault.py:110`, `179-181` |

---

## Risk Matrix

| ID | Title | Severity |
|----|-------|----------|
| F-01 | Record rule join bug — expiry bypass | **HIGH** |
| F-02 | Shared-secret recipients have full write/delete rights | **HIGH** |
| F-03 | Passphrase length not enforced at model layer | MEDIUM |
| F-04 | Failed unseal attempts not logged | MEDIUM |
| F-05 | Share revocation not logged | MEDIUM |
| F-06 | No explicit ownership check on share creation | MEDIUM |
| F-07 | Vault key unavailable in other worker processes | MEDIUM |
| F-08 | No key rotation mechanism | MEDIUM |
| F-09 | Vault UI incorrectly claims AES-256 | LOW |
| F-10 | PBKDF2 iterations below 2023 OWASP recommendation | LOW |
| F-11 | Non-constant-time verifier comparison | LOW |
| F-12 | No maximum share expiration duration | LOW |
| F-13 | `get_vault_state()` accessible to all users | INFO |

---

## Remediation Priority

1. **Immediate (before production use):** F-01, F-02
2. **Short-term (next sprint):** F-03, F-04, F-05, F-06
3. **Medium-term (hardening):** F-07, F-08, F-10, F-11, F-12
4. **Documentation/cosmetic:** F-09, F-13

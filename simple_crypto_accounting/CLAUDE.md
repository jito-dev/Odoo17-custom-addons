# Simple Crypto Accounting

## Purpose
Allows users to configure Ethereum wallet addresses to follow and download their ERC-20 token transaction history via the Etherscan API. Transactions are stored in a read-only ledger for visibility. No journal entries or reconciliation are created.

## Main Models

### `sca.settings`
Singleton configuration record holding the Etherscan API key.
- Enforced as singleton via `lock_field` UNIQUE SQL constraint.
- Use `_get_singleton()` to always retrieve/create the single record.
- Only administrators can write to this model.

### `sca.watched_address`
Represents an Ethereum wallet address the user wants to monitor.
- Has a One2many to `sca.token` (specific ERC-20 contracts to track).
- Has a One2many to `sca.transaction` (downloaded transactions).
- `action_sync()` triggers the Etherscan API fetch for all associated tokens.

### `sca.token`
An ERC-20 token contract to watch, linked to a specific `sca.watched_address`.
- Key fields: `name` (symbol), `contract_address` (0x...), `decimals`.
- USDT/USDC use 6 decimals; most other tokens use 18.

### `sca.transaction`
Ledger of downloaded transactions. Blockchain fields are read-only; users can add a description and file attachments via the chatter.
- `tx_hash` is unique (prevents duplicate imports).
- `raw_value` stores the integer value as a string to avoid float precision issues.
- `value_decimal` is computed: `int(raw_value) / 10^decimals`.
- `direction` is computed: 'in' if `to_address == watched_address.address`, else 'out'.
- `description`: free-text notes field editable by users.
- Inherits `mail.thread` + `mail.activity.mixin` for chatter and file attachments.
- Users have write access (to save description/chatter); blockchain fields remain `readonly=True` in the model and view.

## Business Logic

### Sync Flow (`sca.watched_address.action_sync`)
1. Load API key from `sca.settings` singleton.
2. For each `sca.token` on the address, call Etherscan `tokentx` endpoint.
3. For each transaction row returned, skip if `tx_hash` already exists.
4. Create new `sca.transaction` records.
5. Update `last_sync_date` on the address.
6. Return a `display_notification` with the count of new transactions.

### Etherscan API
- Endpoint: `https://api.etherscan.io/api?module=account&action=tokentx&...`
- Free API key available at etherscan.io/apis (5 req/s, 100k req/day).
- HTTP library: `urllib.request` (no external dependencies needed).

## Security
- `group_sca_user`: Can manage addresses, tokens; can read and write (description/chatter) transactions.
- `group_sca_admin`: Full access including Settings and Remove Duplicates.

## Accounting Injection (v1.3.0)

### Overview
Bridges `sca.transaction` → Odoo accounting by creating `account.bank.statement.line` records. Each `(watched_address, token_symbol)` pair maps to a specific Odoo bank journal via `sca.journal.map`.

### New Model: `sca.journal.map`
Maps `(watched_address_id, token_symbol)` → `journal_id`. SQL unique constraint on the pair. Editable inline tree at Configuration → Journal Mapping.

### Key Fields on `sca.transaction`
- `statement_line_id` (Many2one → account.bank.statement.line): link to injected entry.
- `is_injected` (Boolean, computed/stored): True when linked.
- `crypto_tx_ref` (Char, computed: `{tx_hash}_{log_index}`): unique per ERC-20 event within a transaction.

### Amount & Sign
- Incoming ('in'): `+value_decimal` (money received)
- Outgoing ('out'): `-value_decimal` (money sent)

### Methods
- `action_inject_to_accounting()`: batch creates statement lines with journal lookup, dedup, partner matching.
- `action_remove_from_accounting()`: unreconciles, drafts, deletes.
- `_find_journal_mapping()`: looks up `sca.journal.map` by address + token.
- `_find_partner_for_transaction()`: resolves counterparty via `sca.known_address` → `res.partner`.

### Statement Line Extension
- `crypto_tx_ref` on `account.bank.statement.line` and `account.move.line` (related, stored) for Journal Items traceability.

### UX Flow
1. Configuration → Journal Mapping → create mappings (e.g. WalletA/USDT → Journal X).
2. Transactions → select → Actions → Inject to Accounting.
3. To undo: Actions → Remove from Accounting.

## Important Patterns
- The `sca.settings` singleton uses the same pattern as `upwork_simple_accounting_integration/models/usa_settings.py`.
- All external API calls use `urllib.request.urlopen` for consistency with other jito_modules.
- Transactions are never created/deleted by users — only via `action_sync` / admin delete. Users may edit `description` and add chatter attachments.
- Deduplication: `_sync_eth()` skips rows with `value=0` (ERC-20 contract calls). A `seen_hashes` set is threaded through the sync to catch intra-request duplicates. `action_remove_duplicates()` cleans existing duplicates, keeping the token-linked record.

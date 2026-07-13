# Simple Crypto Accounting

## Purpose
Watch wallet addresses on Ethereum (**ERC-20** via Etherscan) and TRON
(**TRC-20** via Tronscan, 17.0.5.0.0; was CryptoAPIs in 17.0.4.x, TronGrid in 17.0.3.x — CryptoAPIs's REST API doesn't expose TRC-20 transfer listings) and download their token transfer
history into a read-only ledger. Transactions can then be injected
directly into the Management Ledger (`jito.ledger.move`,
entry_type='ext_adjustment') with provenance traces — see the
Management-Ledger Injection section below.

## Main Models

### `sca.settings`
Singleton configuration record holding API keys for each supported
network.
- `etherscan_api_key` — required for ERC-20 syncs (Etherscan free tier).
- `tronscan_api_key` (17.0.5.0.0) — **optional** for TRC-20 syncs.
  Tronscan's public endpoints at `apilist.tronscanapi.com` work
  anonymously for low volume. When set, sent as `TRON-PRO-API-KEY`
  for higher rate limits.
- `cryptoapis_api_key` (deprecated 17.0.5.0.0) — retained on the
  model for migration safety; hidden from the UI. CryptoAPIs's REST
  API doesn't expose TRC-20 transfer listings.
- `trongrid_api_key` (deprecated 17.0.4.0.0) — same status.
- Enforced as singleton via `lock_field` UNIQUE SQL constraint.
- Use `_get_singleton()` to always retrieve/create the single record.
- Only administrators can write to this model.

### `sca.watched_address`
A wallet address to monitor on a chosen `network`:
- `network` (Selection, 17.0.3.0.0): `'erc20'` (Ethereum / Etherscan)
  or `'trc20'` (TRON / Tronscan since 17.0.5.0.0). Drives which API `action_sync()`
  calls and which block-explorer URL appears on transactions.
- Has a One2many to `sca.token` (specific token contracts to track).
- Has a One2many to `sca.transaction` (downloaded transactions).
- `action_sync()` dispatches by `network`:
  - ERC-20 → `_sync_token()` per ERC-20 token + optional `_sync_eth()`
    for native ETH (`sync_eth_transfers=True`).
  - TRC-20 → `_sync_trc20_token()` per TRC-20 token. Native TRX is
    not yet supported (planned follow-up); `sync_eth_transfers` is
    ignored for TRC-20 addresses.

### `sca.token`
A token contract to watch, linked to a specific `sca.watched_address`.
- Key fields: `name` (symbol), `contract_address`, `decimals`.
- `contract_address` format depends on the parent address's `network`:
  ERC-20 = `0x` + 40 hex chars; TRC-20 = base58-encoded `T...`
  (typically 34 chars). The field accepts both — no per-network
  validation in v1.
- USDT/USDC use 6 decimals on both networks; most other tokens use 18.
- `preset_id` (17.0.3.1.0, M2O `sca.token.preset`): pick a well-known
  token to auto-fill Symbol, Contract Address, and Decimals.
  `parent_network` (related/stored from the parent address) drives the
  domain so ERC-20 addresses only see ERC-20 presets, and vice versa.

### `sca.token.preset` (17.0.3.1.0; 17.0.6.0.0 adds currency_id)
Registry of well-known token contracts per network. Seeded via
`data/sca_token_preset.xml` (`noupdate=1`, so user edits survive
upgrades): ERC-20 USDC / USDT / DAI / WETH; TRC-20 USDT / USDC.
Admins manage it at **Configuration → Token Presets**. Picking a
preset on a `sca.token` row triggers `_onchange_preset_id` which
overwrites symbol / contract address / decimals **and currency_id**
from the preset (17.0.6.0.0). Unique on `(network, contract_address)`.

`currency_id` (M2O `res.currency`) links the preset to a real Odoo
currency record — seeded via `jito_crypto_currencies`'s xmlids
(`currency_usdc`, `currency_usdt`, …). The same logical token across
chains reuses **one** currency record (ERC-20 USDC and TRC-20 USDC
both reference `currency_usdc`), so consolidated reports treat them
as a single unit.

### `sca.transaction`
Ledger of downloaded transactions. Blockchain fields are read-only; users can add a description and file attachments via the chatter.
- `tx_hash` is unique (prevents duplicate imports).
- `raw_value` stores the integer value as a string to avoid float precision issues.
- `value_decimal` is computed: `int(raw_value) / 10^decimals`.
- `direction` is computed: 'in' if `to_address == watched_address.address`, else 'out'.
- `description`: free-text notes field editable by users.
- Inherits `mail.thread` + `mail.activity.mixin` for chatter and file attachments.
- Users have write access (to save description/chatter); blockchain fields remain `readonly=True` in the model and view.

### `sca.known_address` (+ Contacts, 17.0.10.0.0)
An address book of crypto wallet addresses. Fields: `address` (required,
`UNIQUE`), `notes`, optional `name`/alias, and **`partner_id`** (M2O
`res.partner`, `ondelete='cascade'`) linking a wallet to a normal Odoo
contact. `display_name` = `name or address`.

**Contacts tab (Crypto app → Contacts).** `res.partner` is extended with
`crypto_address_ids` (One2many to `sca.known_address`) + a
`crypto_address_count`. A dedicated menu `menu_sca_contacts` opens
`action_sca_contacts` on `res.partner` (domain `[('type','=','contact')]`,
top-level contacts), bound via `ir.actions.act_window.view` records to a
**standalone** crypto tree + form (`view_sca_contact_tree` /
`view_sca_contact_form`, modeled on `base.view_partner_simple_form`). The
form has a **Crypto Addresses** tab where you add rows of `(address, note)`.

**"Addresses only in the crypto module" — how it's guaranteed:**
`crypto_address_ids` is on the `res.partner` *model* but referenced only in
`view_sca_contact_form` — we never `xpath` into `base.view_partner_form`, so
the standard Contacts app shows no crypto data (same partner, different
view). The `sca.known_address` rows are also ACL-locked to
`group_sca_user`/`group_sca_admin`, so non-crypto users can't read them at
all.

**Security:** `group_sca_user` implies `base.group_partner_manager` (needed
to write `res.partner` / save the embedded addresses; `base.group_user` is
read-only on partners). Side effect: the standard Contacts app also becomes
visible to crypto users.

**Transaction → Contact link (17.0.10.1.0).** `sca.transaction` computes
`from_partner_id` / `to_partner_id` (non-stored) by matching `from_address` /
`to_address` against contact-linked `sca.known_address` rows. When matched,
the From/To column shows the contact name (via `from_display`/`to_display`)
plus a clickable contact icon: the tree buttons `action_open_from_contact` /
`action_open_to_contact` open the **crypto Contacts form**
(`view_sca_contact_form`, with the Addresses tab); the transaction form shows
the same as clickable M2O links routed via
`context="{'form_view_ref': 'simple_crypto_accounting.view_sca_contact_form'}"`.

## Business Logic

### Sync Flow (`sca.watched_address.action_sync`)
1. Branch by `network`:
   - ERC-20: load Etherscan key from settings (required), call
     `_sync_token()` per `sca.token`, then `_sync_eth()` if
     `sync_eth_transfers=True`. Refreshes ETH and ERC-20 balances.
   - TRC-20: load Tronscan key (optional), call `_sync_trc20_token()`
     per `sca.token`, then `_refresh_trc20_balances()` against
     Tronscan's `/api/account` endpoint.
2. For each transaction row returned, skip if `tx_hash` already
   exists (per `unique_tx_hash` SQL constraint + in-request
   `seen_hashes` set).
3. Create new `sca.transaction` records.
4. Update `last_sync_date` on the address.
5. Return a `display_notification` with the count of new transactions.

### Etherscan API (ERC-20)
- Endpoint: `https://api.etherscan.io/v2/api?module=account&action=tokentx&...`
- Free API key at etherscan.io/apis (5 req/s, 100k req/day).
- HTTP library: `urllib.request` (no external dependencies).

### Native TRX (17.0.5.2.0 — wallet-level toggle; 17.0.9.0.3 — also auto-routed via preset)
Native TRX has **two activation paths**:

1. **Wallet flag** (original 17.0.5.2.0 design): `sca.watched_address`
   carries `sync_trx_transfers` (Boolean) and `trx_balance` (Float).
   Visible on the form only when `network == 'trc20'`. Mirrors the
   ERC-20 `sync_eth_transfers` pattern.
2. **Native preset** (17.0.9.0.0 / 17.0.9.0.3): attaching the
   `preset_trc20_trx_native` preset to a wallet creates a `sca.token`
   row with `contract_address='native'`. In 17.0.9.0.3, `action_sync`
   detects this sentinel and triggers `_sync_native_trx` even if the
   wallet flag is off. The same auto-routing applies to ERC-20 with
   `preset_erc20_eth` → `_sync_eth`. The preset path exists so the
   native side can carry a `res.currency` (TRX / ETH) for pricing
   and currency-mapping; the wallet flag alone wouldn't link to a
   currency record.

When `sync_trx_transfers` OR a native-sentinel token is present,
`action_sync` (TRC-20 branch) calls `_sync_native_trx(api_key, seen_hashes)`:
- `GET /api/transfer?address=…&limit=50&start=0&sort=-timestamp`
- Client-side filter to `tokenName == '_'` (Tronscan's native-TRX
  marker; the same `/api/transfer` endpoint returns mixed TRX + token
  rows).
- Each kept row → `sca.transaction(token_id=False, log_index=-1,
  token_symbol='TRX')` — same convention as `_sync_eth`.

`_refresh_trc20_balances` always writes the wallet's root
`balance` (SUN integer) into `trx_balance` after dividing by
`TRX_DECIMALS=6`. The field is stored unconditionally so toggling the
flag later doesn't leave a stale zero.

17.0.5.1.0 briefly modelled TRX as a token preset with sentinel
`contract_address="_"`. That was reverted in 17.0.5.2.0; the
`migrations/17.0.5.2.0/post-migrate.py` script promotes any user-
created TRX "token" rows into `sync_trx_transfers=True` on their
parent and drops the seeded preset + its xmlid.

### Tronscan API (TRC-20, 17.0.5.0.0)
- Base: `https://apilist.tronscanapi.com`
- Auth: optional `TRON-PRO-API-KEY` header when `tronscan_api_key` is
  set. Anonymous access works for low volume (rate-limited per IP).
- Transfers endpoint (used by `_sync_trc20_token`, **corrected 17.0.11.1.0**):
  `GET /api/token_trc20/transfers?relatedAddress={wallet}&contract_address={contract}&limit=50&start=N`
  Response: `{"token_transfers": [...], "total": N, "rangeTotal": N}`.
  Each item carries `transaction_id`, `from_address`, `to_address`,
  `contract_address`, `quant` (raw integer string in base units),
  `block_ts` (ms epoch), and a `tokenInfo` object with
  `tokenAbbr/tokenName/tokenDecimal/tokenType`.
  `relatedAddress` returns the wallet's **full** history (both sent and
  received) in one newest→oldest paginated stream — a single `start`
  sweep captures both sides, so no `direction` loop is needed. Offset is
  capped at `TRC20_OFFSET_CAP` (10 000); beyond that, timestamp-window
  paging is a follow-up.
  **History note (17.0.11.1.0)** — the sync previously used
  `/api/transfer/trc20?address=&trc20Id=&direction={1|2}`, which turned
  out to return only a small **bounded subset** (a couple dozen rows, no
  `total`, deep offsets empty) — so older transfers were unreachable and
  "Sync Full History" reported 0 new. Switched to
  `/api/token_trc20/transfers`. The row-field parsing is unchanged
  (`transaction_id|hash`, `quant|amount`, `from_address|…|from`,
  `to_address|…|to`, `block_ts|block_timestamp`). Native TRX still uses
  `/api/transfer` (`_sync_native_trx`) with the `direction` loop — revisit
  if it shows the same bounded-subset symptom.
- Balances endpoint (used by `_refresh_trc20_balances`):
  `GET /api/account?address={wallet}`
  Response includes `trc20token_balances: [{tokenId, balance,
  tokenAbbr, tokenName, tokenDecimal}]`. `balance` is the raw
  integer string; we divide by `10^tokenDecimal` (or the token's
  own `decimals` as fallback) to write `sca.token.balance`.
- **Pagination + Full History (17.0.11.0.0).** `_sync_trc20_token` /
  `_sync_native_trx` page via `start` (50/page). Two modes, both driven
  by `sca.watched_address._sync_all(full_history=...)`:
  - **Incremental** (`action_sync`, "Sync Transactions") — capped at
    `TRC20_MAX_PAGES` (20 → 1 000/direction) and **early-stops** when a
    page adds zero new rows (`page_new == 0`). Fast, but since Tronscan
    returns newest-first, a re-run stops at the first already-imported
    page and never back-fills older gaps.
  - **Full history** (`action_sync_full_history`, "Sync Full History"
    button — TRC-20 only) — raises the cap to `TRC20_MAX_PAGES_FULL`
    (400 → 20 000/direction) and **disables the `page_new == 0`
    early-stop**, so it walks newest→oldest to the true end of history
    (a short/empty page), recovering old transfers. Opt-in (many more
    API calls); composite dedup prevents re-imports.
- Block-explorer URL on `sca.transaction`:
  `https://tronscan.org/#/transaction/{tx_hash}`.

If Tronscan returns a different field shape (e.g. an alternative key
like `data` instead of `token_transfers`), the **Debug Sync (TRC-20)**
button on `sca.watched_address` probes both endpoints and dumps the
raw response into a sticky notification — use that to verify, then
adjust the field mapping in `_sync_trc20_token` /
`_refresh_trc20_balances` accordingly.

## Security
- `group_sca_user`: Can manage addresses, tokens; can read and write (description/chatter) transactions.
- `group_sca_admin`: Full access including Settings and Remove Duplicates.

## Management-Ledger Injection (v2.0.0)

### Overview
v2.0.0 **replaces** the v1.3.x stock-LL injection (which created
`account.bank.statement.line` records) with a direct write into the
**Management Ledger**: each `sca.transaction` posts one
`jito.ledger.move(entry_type='ext_adjustment')` with two balanced
lines and two `jito.ledger.trace` rows. Stock Odoo's `account.move`
table is no longer touched.

Rationale: crypto-driven workflows don't fit the bank-statement model
(no reconciliation, no journal items needed in stock accounting), and
the management ledger has a dedicated `ext_adjustment` entry_type +
provenance trace infrastructure already designed for non-Odoo sources.

### New Model: `sca.mgt.ledger.map`
Maps `(watched_address_id, token_symbol)` → destination in the
management ledger. Required fields:
- `journal_id` — must be associated with a Non-Leading or Extension
  jito.ledger via `jito.ledger.journal.rel`.
- `asset_account_id` (jito.ledger.account, MGT.* or FAAP.*) — where
  the token balance sits, e.g. `MGT.CRYPTO.USDT`.
- `counterpart_account_id` (jito.ledger.account, MGT.* or FAAP.*) —
  the other side of every entry, e.g. `MGT.UNCLASSIFIED_INFLOW` for
  inbound txs you'll later reclassify via Restatement / Regrouping.
- `currency_id` (res.currency) — the token's currency (must match
  `asset_account.currency_id` when that's set).

SQL unique constraint on `(watched_address_id, token_symbol)`.
Configured at Configuration → Management Ledger Mapping.

### Key Fields on `sca.transaction`
- `jito_move_id` (Many2one → jito.ledger.move): link to the generated
  management-ledger move.
- `is_injected` (Boolean, computed from `jito_move_id`): True when
  linked.
- `crypto_tx_ref` (Char, computed: `{tx_hash}_{log_index}`): unique
  per ERC-20 event within a transaction.
- `statement_line_id` (Many2one → account.bank.statement.line):
  **retained for historical data**; never written into in v2.0.0+.

### Amount, Sign, Currency
- Direction `in`: DR `asset_account` + CR `counterpart_account`,
  amount = `value_decimal`.
- Direction `out`: CR `asset_account` + DR `counterpart_account`,
  amount = `value_decimal`.

Both lines are in `mapping.currency_id`; the per-currency balance
constraint on `jito.ledger.move` holds because debit/credit are equal
magnitudes in one currency.

### Methods
- `action_inject_to_management_ledger()` (batch): creates
  `jito.ledger.move` + two lines + two trace rows; posts the move;
  writes `jito_move_id` back.
- `action_remove_from_management_ledger()` (batch): resets the
  generated move to draft and unlinks it (lines + traces cascade);
  clears `jito_move_id`. Refuses if the move was reversed / voided.
- `_find_mgt_ledger_mapping()`: lookup on `sca.mgt.ledger.map` by
  (address, token).
- `_crypto_tx_payload()`: builds the `crypto_tx` payload dict per
  `jito_ledger_adjustments/payload_schemas.py` v1 (keys: tx_hash,
  token, amount_decimal, direction, block_number, wallet_address).
- `_find_partner_for_transaction()` (17.0.10.0.0): resolves the
  counterparty (From for inbound, To for outbound) by following
  `sca.known_address.partner_id` directly — a deterministic FK match
  (`UNIQUE(address)` → single row). Replaced the pre-17.0.10.0.0
  fragile `res.partner` name-ilike guess. Returns an empty recordset
  when the address isn't linked to a contact.

### Provenance
Every generated `jito.ledger.move.line` carries a `jito.ledger.trace`
row with `source_payload_kind='crypto_tx'` and the full crypto payload
in `source_payload`. An auditor can query "which crypto tx produced
this management-ledger line" by following the trace; or "which
management-ledger lines came from tx hash 0xabc..." by querying
traces with that payload key.

### UX Flow
1. Configuration → **Management Ledger Mapping** → create mappings
   (e.g. WalletA/USDT → CINV-MGT journal / `MGT.CRYPTO.USDT` /
   `MGT.UNCLASSIFIED_INFLOW` / USDC).
2. Transactions → select rows → header button **Inject to Management
   Ledger** (or list action). One `jito.ledger.move` per tx is
   created and posted.
3. To undo: select rows → **Remove from Management Ledger**.

### Legacy
The v1.3.x `action_inject_to_accounting` + `action_remove_from_accounting`
methods are removed. The `sca.journal.map` model and its menu remain
visible to admins under "Journal Mapping (legacy)" so historical
config is auditable but no new stock-LL injections happen.

## Important Patterns
- The `sca.settings` singleton uses the same pattern as `upwork_simple_accounting_integration/models/usa_settings.py`.
- All external API calls use `urllib.request.urlopen` for consistency with other jito_modules.
- Transactions are never created/deleted by users — only via `action_sync` / admin delete. Users may edit `description` and add chatter attachments.
- Deduplication: `_sync_eth()` skips rows with `value=0` (ERC-20 contract calls). A `seen_hashes` set is threaded through the sync to catch intra-request duplicates. `action_remove_duplicates()` cleans existing duplicates, keeping the token-linked record.

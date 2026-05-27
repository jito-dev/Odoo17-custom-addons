# jito_crypto_currencies — Developer Guidance

## Module Purpose

Make cryptocurrencies (USDC, USDT, DAI, BTC, ETH, …) usable as
first-class `res.currency` records in Odoo by lifting the 3-char ISO
4217 limit, plus seeded entries for the common stablecoins + majors.
Every other module — invoicing, accounting, management ledger,
partner ledger — automatically gains crypto support without further
code changes.

Rate management is **manual** in v17.0.1.0.0 via the standard
Accounting → Configuration → Currencies UI. An automated price feed
(CoinGecko / Tronscan) is a planned follow-up.

## Models

### `res.currency` (inherited)

**File:** `models/res_currency.py`

Two changes:

| Field | Change | Why |
|---|---|---|
| `name` | `size = 10` (was `3` in stock) | Crypto tickers like USDC, USDT, MATIC, LINK don't fit ISO 4217. 10 chars covers every real-world ticker without unbounded width issues in list views. |
| `is_crypto` | New `Boolean`, default `False` | Filter / reporting separation between fiat and crypto. Set on install for the seeded crypto records via `data/res_currency.xml`. User-editable. |

No behaviour changes for existing fiat — the `size` increase is
strictly additive (any 3-char ISO code still fits), `is_crypto`
defaults to False.

## Seed data — `data/res_currency.xml`

Loaded with `noupdate="1"` so user edits (custom symbols, decimal
overrides) survive module upgrades.

| External ID | Name | Decimals | Notes |
|---|---|---|---|
| `currency_usdc` | USDC | 6 | USD Coin |
| `currency_usdt` | USDT | 6 | Tether USD |
| `currency_dai` | DAI | 6 | Dai Stablecoin |
| `currency_btc` | BTC | 8 | Bitcoin |
| `currency_eth` | ETH | 8 | Ethereum — display cap; on-chain wei is 18 but practical accounting precision is 8 |

Same logical token across chains uses the **same** `res.currency`
record (e.g. ERC-20 USDC and TRC-20 USDC both point at
`currency_usdc`) so consolidated reports treat them as one unit.

## Views — `views/res_currency_views.xml`

Three inherits on stock `base` views:

| Inherit of | Adds |
|---|---|
| `base.view_currency_form` | `is_crypto` toggle next to `active` |
| `base.view_currency_search` | "Fiat" / "Crypto" filters |
| `base.view_currency_tree` | `is_crypto` column (optional) |

## Rate management

Manual entry via the standard UI:
**Accounting → Configuration → Currencies → \<crypto\> → Rates** tab.

A rate is a `(date, company_id, rate)` triple; the framework's
`res.currency._convert` and the management-ledger
`_build_rate_map` helper consume it the same way they do fiat rates.
For period-end translation, set rates at month-end; for spot, set the
current rate.

## Downstream integration

### `simple_crypto_accounting` (17.0.6.0.0+)
- `sca.token` and `sca.token.preset` gain `currency_id` (M2O
  `res.currency`).
- The seeded presets reference the matching crypto-currency xmlid
  (e.g. `preset_erc20_usdc.currency_id = currency_usdc`).
- Picking a preset on a `sca.token` row auto-fills `currency_id`.
- `sca.mgt.ledger.map.currency_id` already exists — once crypto
  currencies are real, the user just picks USDC/USDT there. No code
  change needed.

### Management ledger reports
Trial Balance and Partner Ledger's `_build_rate_map` reads
`res.currency.rate` for every currency present in the data. Once
USDC/USDT/etc. are real `res.currency` records with rates, the
existing handlers translate them to company currency at report time
exactly like for fiat — no separate code path.

## Adding more crypto currencies

Two options:
1. **Via UI**: Accounting → Configuration → Currencies → New, tick
   "Is Crypto", set name (e.g. `MATIC`), symbol, decimals. Done.
2. **Via XML**: add a `<record>` to a downstream module's data file
   referencing the same shape as `data/res_currency.xml`. Use
   `noupdate="1"` so user edits stick.

## Out of scope (planned)

- **Automatic rate ingestion** — CoinGecko `/simple/price` or
  Tronscan `tokenPriceInTrx` on a cron, populating `res.currency.rate`
  daily. Same pattern as the existing `jito_ecb_exchange_rate`
  module.
- **Per-currency metadata** — contract addresses across chains,
  logo, market cap, etc. Useful once dashboards land.
- **Decimal precision overrides per company** — `decimal_places` is
  global today; if a company wants USDC at 2 dp for invoicing but 6
  dp for ledger lines, that needs a separate field. Not requested.

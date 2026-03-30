# jito_ecb_exchange_rate — Module Guide

## What it does

Downloads exchange rates from the European Central Bank (ECB) and stores them
as `res.currency.rate` records in Odoo. Supports:

- **Daily auto-download** via a scheduled action (cron) with retry and fallback
- **Manual download** button for the latest ECB rates
- **Historical backfill** wizard for importing rates over a user-chosen date range
- **Sync status tracking** with success/failure display in Settings
- **Admin notifications** when rate downloads fail persistently
- **Stale rate guardrail** — blocks posting invoices with outdated FX rates

## Main Models

| Model | Type | Purpose |
|-------|------|---------|
| `res.company` (inherited) | Model | Core ECB fetch/upsert logic, cron method, retry/fallback, sync tracking, notifications |
| `account.move` (inherited) | Model | Stale rate check on `_post()` — blocks posting with outdated FX rates |
| `ecb.rate.history.wizard` | TransientModel | Historical backfill wizard with date range and source selection |
| `ecb.sync.dashboard` | Model (singleton) | Dashboard showing sync status, rate statistics, cron info, and quick actions |
| `ecb.currency.rate.status` | SQL View | Per-company, per-currency rate status (excludes base currency); used by spreadsheet dashboard |

## ECB Data Sources

| Feed | URL |
|------|-----|
| Daily (latest) | `eurofxref-daily.xml` |
| Last 90 days | `eurofxref-hist-90d.xml` |
| Full history | `eurofxref-hist.xml` |

## Robustness Features

### Retry with Backoff
On network/HTTP failure, retries 3 times with 0s/30s/60s delays before giving up.

### Fallback Data Source
If the daily feed fails after all retries, automatically tries the 90-day history feed
(different CDN/URL, contains the same recent data).

### Sync Status Tracking
Fields on `res.company`:
- `ecb_last_sync_date` — when the last sync attempt happened
- `ecb_last_sync_status` — 'success' or 'failed'
- `ecb_last_sync_error` — error message on failure

Displayed in Settings → Accounting → ECB Exchange Rates with colored badges.

### Admin Notification
On persistent failure (both URLs exhausted), sends an Odoo notification to all
users in the `account.group_account_manager` group.

### Stale Rate Guardrail
When posting (validating) an `account.move` in a foreign currency, checks if the
most recent exchange rate is older than `ecb_stale_rate_days` (default: 3 days).
If stale, raises a `UserError` to prevent posting with potentially wrong FX.
Set threshold to 0 to disable.

## Business Logic

- Rates are fetched as XML, parsed with `lxml.etree` using XPath with the ECB namespace.
- All ECB rates are EUR-based. They are **normalized** to the company's base currency:
  `rate_value = ecb_rate / ecb_rate_of_company_currency`.
- Rates are written via the `company_rate` field (the user-visible rate) rather than the
  technical `rate` field. Odoo's `_inverse_company_rate` derives the correct technical
  value automatically.
- The company's own base currency is skipped (always implicitly 1.0 in Odoo).
- Only active currencies in Odoo are processed.
- Existing rates are updated (not duplicated) — matched by `(currency_id, date, company_id)`.
- Large imports batch-commit every 500 records to avoid long transactions.

## Views

- **Settings**: Invoicing → Configuration → ECB Exchange Rates (sync status, threshold, buttons)
- **Historical wizard**: modal dialog with date range, source selection, and result display
- **Spreadsheet Dashboard**: Dashboards app → Infrastructure → ECB Exchange Rates
  - Scorecards: Last Sync (date + "X days ago"), Outdated Currencies (red when >3 days stale)
  - Currency rate table: all active currencies except company base (zebra-striped, sorted alphabetically)
  - Exchange rate trend line chart: shows rate history from `res.currency.rate`
  - Global filters: Currency (relation filter) and Period (date, defaults to last 3 months)
  - Multi-company aware: SQL view cross-joins with companies, record rule filters by company
- **Detail Dashboard**: `ecb.sync.dashboard` singleton form view (accessible via Settings buttons)
  - Stat buttons, sync status badges, cron info, quick actions

## Constraints

- Depends on `base`, `account`, `mail`, and `spreadsheet_dashboard`.
- Company base currency must be available in the ECB feed (EUR + ~30 currencies).
- ACL: account managers can use the wizard; account users have read-only access.

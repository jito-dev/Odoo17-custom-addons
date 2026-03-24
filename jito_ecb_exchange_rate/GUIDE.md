# jito_ecb_exchange_rate — Module Guide

## What it does

Downloads exchange rates from the European Central Bank (ECB) and stores them
as `res.currency.rate` records in Odoo. Supports:

- **Daily auto-download** via a scheduled action (cron)
- **Manual download** button for the latest ECB rates
- **Historical backfill** wizard for importing rates over a user-chosen date range

## Main Models

| Model | Type | Purpose |
|-------|------|---------|
| `res.company` (inherited) | Model | Core ECB fetch/upsert logic, cron method, daily download button |
| `ecb.rate.history.wizard` | TransientModel | Historical backfill wizard with date range and source selection |

## ECB Data Sources

| Feed | URL |
|------|-----|
| Daily (latest) | `eurofxref-daily.xml` |
| Last 90 days | `eurofxref-hist-90d.xml` |
| Full history | `eurofxref-hist.xml` |

## Business Logic

- Rates are fetched as XML, parsed with `lxml.etree` using XPath with the ECB namespace.
- All ECB rates are EUR-based. They are **normalized** to the company's base currency:
  `rate_value = ecb_rate / ecb_rate_of_company_currency`.
- Rates are written via the `company_rate` field (the user-visible rate) rather than the
  technical `rate` field. Odoo's `_inverse_company_rate` derives the correct technical
  value automatically. This ensures the displayed rate always matches the ECB value
  regardless of pre-existing rate records on the company's base currency.
- The company's own base currency is skipped (always implicitly 1.0 in Odoo).
- Only active currencies in Odoo are processed.
- Existing rates are updated (not duplicated) — matched by `(currency_id, date, company_id)`.
- Large imports batch-commit every 500 records to avoid long transactions.

## Views

- **ECB Exchange Rates** form: shows company info + two action buttons
- **Historical wizard**: modal dialog with date range, source selection, and result display
- **Menu**: Invoicing → Configuration → ECB Exchange Rates

## Constraints

- Depends on `base` and `account` only (no enterprise dependency).
- Company base currency must be available in the ECB feed (EUR + ~30 currencies).
- ACL: account managers can use the wizard; account users have read-only access.

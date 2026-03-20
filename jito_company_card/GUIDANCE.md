# jito_company_card — Company Business Card

## What it does
Generates a publicly accessible, beautifully styled company card page that can be shared with potential business partners via a unique token-based URL.

## Main models
- **res.company** (extended) — adds `card_share_token`, `card_published`, and computed `card_share_url` fields.

## Views
- **Backend**: "Company Card" tab in the company form (Settings > Companies) with publish toggle, share URL, and token regeneration button.
- **Public page**: QWeb template at `/company/card/<token>` — beautiful card showing company name, address, website, VAT, logo, and director email.

## Business logic
- Token is auto-generated (UUID) on company creation.
- Card is only accessible when `card_published = True`.
- Token can be regenerated to revoke old links.
- Director email is pulled from `hpc_representative_id` (Authorized Representative from `hr_payroll_for_contractors`).
- Address is concatenated from street, street2, city, state, zip, country.

## Dependencies
- `website` — for public page rendering and `website.layout` template.
- `hr_payroll_for_contractors` — for the `hpc_representative_id` field on res.company.

## Patterns & constraints
- Controller uses `.sudo()` for public read access to company data.
- No new security rules needed (no new models).
- Fields with no data are gracefully hidden on the card.

# VAT Checker Module

## What It Does

Extends the `res.partner` (Contacts) form with a **"Request VAT Info"** button that
validates EU VAT numbers via the official [VIES REST API](https://ec.europa.eu/taxation_customs/vies/).

- Button is visible only on **Company** contacts that have a **Tax ID** (`vat`) set.
- Tax ID is expected in the format `<2-letter-EU-code><VAT-number>`, e.g. `PL6793294352`.
- On success the result is stored on the partner and a **VAT Info** tab becomes visible.

## Main Models

### `res.partner` (inherited)

New fields:

| Field | Type | Description |
|---|---|---|
| `vat_check_valid` | Boolean | Whether VIES returned `isValid: true` |
| `vat_check_date` | Datetime | Timestamp of the last check |
| `vat_check_name` | Char | Company name as registered in VIES |
| `vat_check_address` | Text | Registered address from VIES |
| `vat_check_user_error` | Char | VIES status string (e.g. `VALID`, `INVALID`) |
| `vat_check_request_id` | Char | VIES request identifier |
| `vat_check_original_vat` | Char | The exact VAT number that was checked |

### Method `action_check_vat()`

1. Calls `_parse_vat_number(vat)` to split the Tax ID into `(ms_code, number)`.
2. Builds the VIES URL: `https://ec.europa.eu/taxation_customs/vies/rest-api/ms/{ms}/vat/{vat}`.
3. Performs an HTTP GET with a 15-second timeout using `urllib` (no extra dependencies).
4. Writes the response fields and shows a `display_notification` toast.

## Views

`views/res_partner_views.xml` inherits `base.view_partner_form`:

- Injects the **"Request VAT Info"** button after the `vat` field (visible only for companies with a Tax ID).
- Adds a **"VAT Info"** notebook page (visible only after a check has been performed).

## Supported EU Member States

All 28 VIES member states: AT, BE, BG, CY, CZ, DE, DK, EE, EL, ES, FI, FR, HR, HU, IE, IT,
LT, LU, LV, MT, NL, PL, PT, RO, SE, SI, SK, XI (Northern Ireland).

## Important Constraints

- Only company contacts (`is_company = True`) with a populated Tax ID can trigger a check.
- The check does **not** auto-run on save; it is always user-initiated via the button.
- All result fields are `readonly` and `copy=False` to prevent accidental modification.
- No additional Python packages are required; `urllib` (stdlib) is used for HTTP calls.

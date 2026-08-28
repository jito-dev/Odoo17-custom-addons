# account_portal_transfer_details — guidance

## What the module does

Shows the **bank transfer details of an invoice** on the customer portal
(`/my/invoices/<id>`), as a card where every value copies on click and one button
copies the lot as plain text.

It replaces what stock Odoo offers for wire transfer: `payment_custom`'s
`action_recompute_pending_msg()` pastes the IBANs of *every* bank journal into the
provider's *Pending Message* and shows that after the customer clicks Pay — no
beneficiary, no BIC, no amount, no reference, and the same list on every invoice
whatever its currency.

## Main components

| File | Responsibility |
|---|---|
| `models/account_move.py` | `_get_transfer_details()` builds the rows from the invoice; `_get_transfer_provider()` decides whether transfers are offered at all; `_get_transfer_copy_all()` renders the plain-text version. |
| `models/payment_provider.py` | The two values the card cannot infer: contact email and the purpose template. |
| `views/portal_templates.xml` | The card template, the icon set, and the insertion into `account.portal_invoice_page`. |
| `views/payment_provider_views.xml` | The two settings, shown only for a Wire Transfer provider. |
| `static/src/scss/transfer_card.scss` | The card's own visual identity, fully scoped under `.o_transfer_section`. |
| `static/src/js/transfer_card.js` | Copying, the copied state, and the screen-reader announcement. |

## Business logic worth knowing

**Nothing is stored.** The rows are read from the invoice at render time. Change
the Recipient Bank and the card follows on the next page load; there is no cache to
invalidate and no second copy of the bank details to drift.

**The amount is what is still due.** `amount_residual`, never `amount_total`. After
a partial payment a customer told the total transfers the whole invoice a second
time. This is the single most expensive thing this module can get wrong, and it is
the first thing its tests check.

**What is displayed and what is copied are different strings.** The IBAN reads
grouped (`LT74 3250 …`) and copies unspaced, because bank forms refuse the spaces.
The amount reads `2,320.00 USD` and copies `2320.00`, because an amount field takes
digits — no grouping separator, no currency code. Each row therefore carries its own
`copy` value, defaulting to the displayed one.

**The currency is shown as its ISO code, not its symbol.** `$` is three different
currencies, and this number is retyped into an international transfer.

**A half-filled card is worse than none.** With no Recipient Bank, no account
number, or no BIC on the bank, `_get_transfer_details()` returns `[]` and the card
does not render — a transfer sent without a BIC is refused by the correspondent
bank or sits in limbo for weeks, and a dash on screen looks deliberate rather than
missing. Every refusal is logged with the invoice name and what exactly was missing.

**The card is not a payment method.** It sits *after* the payment block, not among
the "Pay now" options, and creates **no** `payment.transaction`. Paying by transfer
is not an online payment: Odoo never sees the money, and the invoice is closed from
the bank statement days later. Putting it among the online options would promise a
confirmation that never comes — and stock Odoo's version of that promise is why
`INV/2026/00340` carries three `pending` transfer transactions that mean nothing.

**Odoo's own panel is suppressed, narrowly.** As soon as a transaction is pending,
`account_payment` renders `payment.transaction_status` on the invoice page, and
`payment_custom` turns that into "Finalize your payment" followed by the
bank-account dump this module replaces — two sets of transfer details on one page,
and the customer has to decide which to trust.
`portal_invoice_hide_stock_transfer_status` adds one clause to that panel's `t-if`:
it is hidden **only** when the last transaction is a wire transfer **and** this
module actually rendered a card. Every other provider keeps its panel, and an
invoice whose details are too incomplete for a card falls back to Odoo's.

**The provider still gates it.** No enabled Wire Transfer provider for the
company — or one whose `available_currency_ids` excludes the invoice currency — and
there is no card. The same rule the portal applies to every other payment method.

## The card

It reads as a document, at the density of the portal page around it — the first
version was built to a brief written for a standalone page and was far too heavy
once it sat under an invoice. Points that are easy to undo by accident:

- **Hairlines carry the separation, not whitespace.** Rows are divided by
  `inset 0 1px 0` box-shadows, which is what keeps eleven values compact and still
  scannable. Replacing them with a `gap` doubles the height of the card.
- **The text must not move on hover.** Rows carry permanent `padding: 9px 10px`
  with a matching negative margin, and only the background colour changes. Adding
  padding on hover brings the jump back.
- **The confirmation is a tick at the end of the row.** Nothing resizes and the
  value stays put — the customer may still be reading it off the screen.
- **The copy-all button must not change width.** Both labels share one grid cell
  (`grid-area: 1 / 1`) and swap by `visibility`, so the longer one sizes the button.
- **The hint** is driven by `:has(.o_transfer_row:hover)` on the card, plus
  `:focus-visible` so the keyboard path shows it too.
- **No web font is loaded.** The stack is `"Source Serif 4", Georgia, serif` and
  **Georgia is what renders** — fetching a font from a third party on every portal
  page a customer opens is a decision with privacy consequences, not a detail. To
  get the intended face, self-host it; the stack then needs no change.
- Everything is scoped under `.o_transfer_section`. The portal around it is
  Bootstrap and must stay untouched.

## Constraints

- Depends on `account_payment` and `payment_custom`; no new models, no ACLs.
- The portal has no dark theme, so the palette is stated once and never inverted.
- `res.partner` and `res.bank` spell the country differently (`country_id` against
  `country`); `_transfer_format_address` reads it defensively rather than assuming.
- The purpose template replaces `{reference}` only. Anything else is copied as it is.

## Tests

`tests/test_transfer_details.py` — 9 tests: the values come from the invoice, the
amount is the residual, the copied strings are bank-safe, the purpose carries the
reference, and the card refuses to render without a Recipient Bank, without a BIC,
without an enabled provider, or in a currency the provider excludes.

Mutation-checked: turning `amount_residual` into `amount_total`, or copying the
IBAN with its spaces, fails two of them.

```bash
odoo-bin -d odoo_test_bankname \
  --addons-path=<community>,<enterprise>,<jito_modules> \
  --without-demo=all --http-port=8199 \
  -u account_portal_transfer_details --test-enable \
  --test-tags /account_portal_transfer_details --stop-after-init --log-level=test
```

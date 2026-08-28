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

A panel that sits *inside* the invoice page rather than on top of it: the same
`$card-bg`, `$border-color`, `$card-border-radius` and full width as everything else
there. The single job is getting the right values into a clipboard without a
transcription error, so the card is quiet everywhere except the amount, the payment
reference, and the moment a copy lands.

**Nothing is a literal colour.** Everything derives from the theme's own Bootstrap
variables, so re-theming the database re-themes the card. Colour carries two jobs
here and they deliberately do not share a variable:

| Role | Variable | Used by |
|---|---|---|
| Structure — the site's voice | `$primary` | reference rule, focus ring, hover border |
| Confirmation — a state, not a brand | `$success` | "Copied", lit blocks, tick, toast |

The split is not decoration. `$primary` on this database is **black** — a black
"copied" highlight on black text is no highlight at all, and any theme is free to
pick a primary that collides with its own body colour. A success state is the one
thing that must stay visible whatever the brand does.

There is **no dark mode to follow**: Odoo 17 ships Bootstrap 5.1.3, which predates
`data-bs-theme`, and the portal has no dark variant. Because the card is built on
theme variables rather than literals, a database that later gains a dark theme gets a
dark card for free.

**Three groups, not a list.** *Who gets paid* / *Where it goes* / *What to write in
the transfer* mirror the three sections of a bank transfer form, so the customer
fills theirs top to bottom without hunting. They are not numbered — they are not a
sequence.

**The reference carries the only structural emphasis** (`inset 2px 0 0` in lemon). A
missing reference is the most common payment error and the reason an accountant
cannot match money to an invoice. No badge, no banner, no extra sentence.

**Four things happen on a copy**, and they are the design:

1. a lemon wipe sweeps behind the row content and collapses out to the right (720ms);
2. the label window slides to reveal "Copied" — two spans in a 14px `overflow:hidden`
   box, `translateY(-100%)`;
3. the copy glyph cross-fades into a check, each scaling from `.6` as it leaves;
4. the signature: a monospace value is split by JS into blocks — an IBAN by four,
   everything else as one — and each block turns lemon and lifts 2px, staggered 45ms.

That last one is the memorable moment; everything else stays quiet on purpose, and
adding more animation only dilutes it.

**Rules that are easy to break by accident:**

- The wipe needs `isolation: isolate` on the row and `z-index: -1` on the
  pseudo-element, or it paints over the text.
- Repeat clicks restart the animation by removing the class, reading `offsetWidth`,
  and re-adding it. Without the reflow the keyframes continue instead of starting.
- Rows are `tabindex="0" role="button"` and answer Enter **and** Space, with
  `preventDefault` on Space so the page does not scroll away under the customer.
- The copy affordance is `opacity: 0` at rest and revealed on hover or focus, so the
  card reads as a document until it is used.
- **No web font is loaded.** The brief names Familjen Grotesk and IBM Plex Mono; the
  portal would have to fetch them from a third party on every page a customer opens,
  so the stacks are the system grotesque and the system monospace. Self-host the two
  faces to get them, and only the two `--jt-ui` / `--jt-mono` values change.
- Every class is `jt-` prefixed and everything nests under `.jt-pay`, so nothing
  reaches Odoo's Bootstrap layer.

**Odoo's own panel is suppressed, narrowly.** As soon as a transaction is pending,
`account_payment` renders `payment.transaction_status`, and `payment_custom` turns
that into "Finalize your payment" followed by the bank-account dump this module
replaces. `portal_invoice_hide_stock_transfer_status` adds one clause to that panel's
`t-if`: hidden **only** when the last transaction is a wire transfer **and** a card
was actually rendered. Every other provider keeps its panel.

**`jt_pay_row` is the reusable row.** QWeb raises on an undefined variable, so every
`t-call` sets `label`, `value`, `copy`, `mono` and `ref` explicitly — defaults
included. `mono` is `-1` proportional, `0` monospace, `4` monospace lit in fours.

## Two things beyond the requisites

**Due date.** The amount answers "how much"; `_get_transfer_due_note()` answers "by
when", which is the question that decides whether the reader pays now or files it. An
overdue invoice says *"Overdue by 3 days"* in `$danger` rather than printing a date
the reader has to compare against today themselves. No due date on the invoice means
no line — inventing one is worse than the silence.

**What was already paid.** After a partial payment the card shows a figure smaller
than the one the customer was sent, and they have no way to tell a discount from an
error from their own money. `_get_transfer_settled_note()` says *"400.00 of 1,000.00
already paid"*, which is also the only acknowledgement they get that the earlier
payment arrived.

> A "Scan to pay" SEPA QR was built and then removed. It is EUR-only by standard —
> which already excludes most invoices here — and `reportlab` cannot render one in
> this environment at all: neither `rlPyCairo` nor `_rl_renderPM` is installed, and
> `build_qr_code_base64`'s `silent_errors` does not cover a rendering failure, so a
> EUR invoice would have reached the customer as a 500. Rather than ship a feature
> that can never appear, it was dropped. Reviving it needs the drawing backend
> installed, `account_qr_code_sepa` back in `depends`, and the call kept inside a
> `try` regardless.

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

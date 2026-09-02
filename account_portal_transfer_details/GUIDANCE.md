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
| `models/payment_provider.py` | The two values the card cannot infer: contact email and the purpose *template*. |
| `models/product_template.py` | `transfer_purpose_name` — how a product is named to a bank, when its catalogue name will not do. |
| `views/portal_templates.xml` | The card template, the icon set, and the insertion into `account.portal_invoice_page`. |
| `views/payment_provider_views.xml` | The two settings, shown only for a Wire Transfer provider. |
| `views/account_move_views.xml` | `transfer_purpose` in the invoice header, right under the payment reference. |
| `views/product_views.xml` | `transfer_purpose_name` on the product's *Accounting* page. |
| `migrations/17.0.4.0.0/post-migrate.py` | Moves the untouched old default onto `{services}`. |
| `static/src/scss/portal_payment.scss` | The card's visual identity: the design tokens, the fold, the rows, the copied state. |
| `static/src/js/portal_payment.js` | Copying, the copied state, the toast, and forcing the card open before printing. |

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

**The currency is also a field of its own** (v17.0.4.1.0), sitting with the amount
because that is where a bank transfer form asks for it. It reads as a suffix on the
amount (`2,320.00 USD`), but the amount *copies* as bare digits — a bank rejects a
currency code in an amount box — so before this row the currency was in nothing the
customer could actually copy, and "Copy all details" pasted a figure with no currency
at all. Rows whose `hero` is set are the ones rendered under the big figure and are
skipped by the grouping; everything else must carry a `section`, or `_get_transfer_card()`
has nowhere to put it.

**A half-filled card is worse than none.** With no Recipient Bank, no account
number, no BIC on the bank, or a bank account whose currency is not the invoice's,
`_get_transfer_details()` returns `[]` and the card does not render — a transfer sent without a BIC is refused by the correspondent
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

**The account currency must be the invoice currency** (v17.0.4.2.0). An account
carrying a currency accepts that currency; money sent in another one is converted at
the beneficiary bank's rate or returned days later, and the customer was quoted an
exact figure. This is not hypothetical here: stock `_compute_partner_bank_id`
(`account/models/account_move.py:893`) picks the first bank account of the partner
without looking at the currency at all, which is how five open invoices came to carry
a EUR account for a USD amount; and `account_journal.py:634-636` rewrites
`bank_account_id.currency_id` whenever the linked journal's currency is edited, so an
invoice and its account can drift apart with nobody touching either. An account with
**no** currency is not a mismatch — empty means "any currency", the same reading
`available_currency_ids` gets, and the field is left empty on most databases.

**The provider still gates it.** No enabled Wire Transfer provider for the
company — or one whose `available_currency_ids` excludes the invoice currency — and
there is no card. The same rule the portal applies to every other payment method.

## The card (rebuilt in v17.0.5.0.0)

A panel that sits *inside* the invoice page rather than on top of it, and is meant to be
indistinguishable from the rest of an Odoo Bootstrap 5 portal page: no branding of its own,
no decorative gradient, no glow, no glass, no emoji. The single job is getting the right
values into a clipboard without a transcription error, so emphasis is spent on exactly three
things — the amount, the payment reference, and the moment a copy lands.

**It folds, and the browser does the folding.** The card is a `<details>` whose `<summary>`
is the header. No JavaScript is involved, so it still folds on a page whose assets failed,
and it is keyboard-operable for free.

**It starts closed** (v17.0.5.1.0). The header alone answers the two questions somebody
opening an invoice actually has — how much, and by when — and it carries the button that
copies the whole lot, so most customers never open the twelve rows underneath at all. Open
by default, those rows pushed the invoice itself off the first screen on every visit,
including every visit by somebody who was never going to pay by transfer.

That is one line in `transfer_details_card` — the `open` attribute on the `<details>` — and
nothing else depends on it. The state is not remembered between page loads, deliberately:
`localStorage` for it would mean a customer who opened the card once gets a different
invoice page from a colleague looking at the same invoice, for no gain.

### Design tokens

Every colour in `portal_payment.scss` is one of these and there are no others:

| Token | Value | Role |
|---|---|---|
| `--jt-primary` / `--jt-primary-hover` | `#000000` / `#212529` | "Copy details" button, focus ring |
| `--jt-ink` | `#212529` | body text, toast ground |
| `--jt-muted` | `#6c757d` | labels, eyebrow, due date, chevron |
| `--jt-bg` / `--jt-surface` / `--jt-surface-hover` | `#ffffff` / `#f3f2f2` / `#ecebeb` | card, header and group titles, hover |
| `--jt-border` / `--jt-border-soft` | `#dee2e6` / `#e9ecef` | card and header rules / row rules |
| `--jt-success` / `--jt-danger` | `#198754` / `#dc3545` | "Copied" / an overdue invoice |
| `--jt-radius` | `.375rem` | the *only* radius on the card |

Two decisions inside that table are worth keeping:

**The values are literals, not the theme's Bootstrap variables.** Earlier versions derived
everything from `$primary`, `$success` and friends so that re-theming the database re-themed
the card. That is the wrong trade here: this card is a fixed piece of design, and a theme
that moves `$primary` to its own brand repaints the copy button and the focus ring with it
for no gain. The values are the portal's own defaults, so on an unthemed database the card
*is* the page.

**The prefix is `--jt-`, not `--o-`.** Odoo owns the `--o-` custom-property namespace
(`--o-color-1` and friends), and writing into it from an addon is how a portal page starts
looking different on the pages this card is not on.

One radius, three font weights (500/600/700), one type scale. The monospace stack is only
for machine-readable values — IBAN, BIC, VAT, the reference, the figure — because a
monospace digit is the one that gets checked by eye against a bank form.

### The header

Icon tile, then the amount, then what is on the right: the due date, "Copy details", the
chevron.

The **amount is a button**, not a heading: it is the value most often typed first, and one
click in the header saves opening the card at all. The figure carries the ISO currency code
next to it and never the symbol — `$` is three different currencies and this number is
retyped into an international transfer.

After a partial payment the header shows what is **still due**, with
`_get_transfer_settled_note()` underneath it in small muted type. Without that line the
customer sees a figure smaller than the one they were sent and cannot tell a discount from
an error from their own money.

An overdue invoice turns the due date `--jt-danger` and bumps it to weight 600. That is the
whole treatment — no banner.

Folded, the header's bottom border goes transparent, or a closed card leaves a line hanging
under itself.

### The rows

Every row is a real `<button type="button">` with an `aria-label` of the form
`Copy IBAN`. That is where Enter, Space, the focus ring and the accessible name come from,
and none of it is implemented in the widget — the previous `tabindex="0" role="button"`
version had to hand-roll all four and got Space wrong until it was patched.

The grid is `minmax(150px, 32%) 1fr auto`: label, value, copy glyph. Rows inside a group are
separated by a `--jt-border-soft` hairline through `.jt-row + .jt-row`, so the last row of a
group never carries a dangling rule.

**The reference carries the only emphasis in the body, and it is weight alone.** A rule, a
tint or a badge would read as a warning about the *value* rather than about typing it. A
missing reference is still the most common payment error and the reason an accountant cannot
match money to an invoice.

### The copied state

Deliberately quieter than what it replaced — the lemon wipe, the sliding label window and
the staggered per-block lift are gone, and what is left is what a customer actually needs to
know:

1. the label is replaced by **Copied** in `--jt-success` with a tick; the label and its
   replacement share one grid cell, so the value column cannot shift under them;
2. the copy glyph becomes a tick and drops its frame;
3. the **value does not change and does not disappear** — it is the thing they look back at
   to check what they took;
4. a toast at the bottom of the viewport names what landed: *"IBAN copied"*, never just
   *"Copied"*, because a click can miss by one row.

Only ever one row is lit. Two would leave the customer unsure which value they have.
"Copy details" turns `--jt-success` and swaps its label for *All details copied*; both
labels share a grid cell so the header does not jump.

### Rules that are easy to break by accident

- **The amount and "Copy details" live inside the `<summary>`.** Their handlers need
  `preventDefault()` *and* `stopPropagation()`, or copying folds the card shut.
- **The IBAN is shown in fours as separate spans held apart by `margin-right: .5ch`** — never
  as spaces in the text. Many bank forms refuse the spaces, and this way a selection made by
  hand yields the same unbroken run of characters the copy button does.
- **What is copied is `data-copy`,** which is not what is on screen: the IBAN unspaced, the
  amount as bare digits with no grouping separator and no currency code.
- **`_copy()` needs the textarea fallback.** `navigator.clipboard` requires a secure context,
  and an on-premise portal served over plain HTTP is not one. When both paths fail the toast
  says *"Press Ctrl/Cmd+C to copy"* — silence would leave the customer wondering whether the
  click registered.
- **Printing is forced open from JS** (`beforeprint` / `afterprint`), because a closed
  `<details>` renders nothing at all: a customer who folded the card and hit print would be
  handed a header with no bank details under it. CSS alone cannot do this. `@media print`
  then drops the copy glyphs, the button, the chevron and the toast.
- **The toast lives outside `.jt-card`.** It is `position: fixed`, and the card sets
  `overflow: hidden` — a card that later gains a transform or a filter would clip the toast
  back inside itself.
- Focus rings are drawn *inside* rows (`outline-offset: -2px`, plus `position: relative` and
  `z-index: 1`) and *outside* buttons (`+2px`). The card clips its overflow, so a ring drawn
  outward on a full-width row is cut off at both ends.
- **No web font is loaded.** The stacks are the system UI grotesque and the system monospace;
  the portal would otherwise fetch a third-party font on every page a customer opens.
- Every class is `jt-` prefixed and everything nests under `.jt-pay`, so nothing reaches
  Odoo's Bootstrap layer — and no class is named `.row`, `.card`, `.btn` or `.col`, which on
  a portal page would redefine the grid around the card.

### Below 576px

The header wraps, the figure drops to `1.3rem`, and "Copy details" becomes its icon alone —
the label is what makes the button wide enough to push the chevron onto a line of its own.
Each row restacks into `1fr auto`: label on the first line, value on the second, the copy
glyph in a second column spanning both and centred against them.

**Odoo's own panel is suppressed, narrowly.** As soon as a transaction is pending,
`account_payment` renders `payment.transaction_status`, and `payment_custom` turns that into
"Finalize your payment" followed by the bank-account dump this module replaces.
`portal_invoice_hide_stock_transfer_status` adds one clause to that panel's `t-if`: hidden
**only** when the last transaction is a wire transfer **and** a card was actually rendered.
Every other provider keeps its panel.

**`jt_pay_row` is the reusable row.** QWeb raises on an undefined variable, so every `t-call`
sets `label`, `value`, `copy`, `mono` and `ref` explicitly — defaults included. `mono` is
`-1` proportional, `0` monospace, `4` monospace split into blocks of four.

**Four groups, not a list.** *How much* / *Who gets paid* / *Where it goes* / *What to write
in the transfer* mirror the sections of a bank transfer form, so the customer fills theirs top
to bottom without hunting. The first is `card['hero_rows']` — the amount and the currency —
titled in the template rather than in the model, because `_get_transfer_card()` keeps them out
of `groups` on purpose and a test asserts that. They are rows like any other despite the
figure in the header: the header figure is a heading, and a heading is not something a
customer expects to copy field by field.

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

## The payment purpose (v17.0.4.0.0)

The purpose line used to be one string on the provider with `{reference}` substituted
into it, which meant **every** invoice told the customer the same thing — in this
database, that they were paying for software development services, whatever they had
actually bought.

The template on the provider is now the **format**, and what the invoice is for comes
from the invoice through a second placeholder, `{services}`. The default is
`{services} – Invoice {reference}`.

`_get_transfer_services()` returns the first of:

1. `account.move.transfer_purpose` — the override on the invoice itself;
2. the distinct `product_id.transfer_purpose_name or product_id.name` of the product
   lines, joined with commas;
3. for a line with no product, the **first line** of its description — a line billed
   from timesheets carries the period, the hours and the rate underneath its title,
   and none of that means anything to a bank;
4. nothing, in which case the placeholder disappears together with the separator it
   was written next to, leaving `Invoice INV/2026/00341` rather than
   `– Invoice INV/2026/00341`.

Each step is a place somebody can correct the one below it: the product for a name
that is wrong on every invoice, the invoice for a name that is wrong on one.

### Length, which is the other half of the work

There was no sanitisation at all before, and a multi-line timesheet description could
go straight into the field. A bank transfer carries **140 characters** of free-text
purpose — SEPA unstructured remittance information, and SWIFT MT103 `:70:` at 4 × 35.
Past it the text is truncated by the bank or the payment is refused.

So `_get_transfer_purpose()`:

- collapses newlines and repeated spaces to single spaces (`_transfer_clean_text`);
- shortens **only the services** to the room the rest of the line leaves
  (`_transfer_shorten`). Cutting the whole string would eat the reference off the
  end, and a transfer that arrives without a reference cannot be matched to an
  invoice by anyone — the single failure this card exists to prevent;
- marks a shortened description with three **ASCII** dots. `…` is not in the SEPA
  character set, and a bank that validates strictly refuses the field over it.

The room is measured with the placeholder still in the string, minus its own length —
measuring the string with it removed collapses the space it stood between and comes
out one character too generous, which is exactly one character off the end of the
reference.

A template that does **not** contain `{services}` is left exactly as it was. Somebody
who phrased their own line meant that line.

### Why there is a migration

`default=` only runs for new records. Every database that already had this module
carries the old fixed string in `payment_provider`, so upgrading alone would change
nothing on the portal. `migrations/17.0.4.0.0/post-migrate.py` rewrites the template
**only where it is byte-for-byte the old default**; anything edited by hand stays as
it is, because overwriting somebody's configuration to improve it is how a fix becomes
a regression.

### Copy-all needed no code

`_get_transfer_copy_all()` builds its text from the same rows, through `row['copy']`,
which falls back to `row['value']`. The new purpose reaches the clipboard on its own —
that is covered by a test rather than by code.

## Constraints

- Depends on `account_payment` and `payment_custom`; no new models, no ACLs.
- The portal has no dark theme, so the palette is stated once and never inverted.
- `res.partner` and `res.bank` spell the country differently (`country_id` against
  `country`); `_transfer_format_address` reads it defensively rather than assuming.
- The purpose template replaces `{reference}` and `{services}` only. Anything else is
  copied as it is, and the result is capped at 140 characters.
- Product names are translatable and the purpose is built in the language of whoever
  loads the portal page; a bank reads it, not the customer. `transfer_purpose_name` is
  the way out until somebody decides the purpose must always be in one language.

## Tests

`tests/test_transfer_details.py` — 29 tests: the values come from the invoice, the
amount is the residual, the copied strings are bank-safe, the purpose carries the
reference, and the card refuses to render without a Recipient Bank, without a BIC,
without an enabled provider, in a currency the provider excludes, or when the bank
account is in a different currency from the invoice. Ten of them cover
the payment purpose: the chain from invoice to product to line description, the 140-character
cap with the reference surviving it, one line with no doubled spaces, no dangling separator
when there is nothing to name, a template without the placeholder left alone, and the
services reaching the copy-all text. Two cover the currency as a displayed
value: that it is its own copyable row carrying the ISO code, and that it stands with the
amount rather than being repeated inside a section. Three more cover it as a guard: a card
refused when the account is in another currency, and rendered both when the account matches
the invoice and when it carries no currency at all.

Mutation-checked: turning `amount_residual` into `amount_total`, or copying the
IBAN with its spaces, fails two of them.

```bash
odoo-bin -d odoo_test_bankname \
  --addons-path=<community>,<enterprise>,<jito_modules> \
  --without-demo=all --http-port=8199 \
  -u account_portal_transfer_details --test-enable \
  --test-tags /account_portal_transfer_details --stop-after-init --log-level=test
```

# payment_revolut — guidance

## What the module does

Adds **Revolut** as an Odoo payment provider. When the customer clicks *Pay now*
on a portal invoice or sales order, Odoo creates a Revolut *order* through the
Merchant API and redirects the customer to the Revolut-hosted payment page. No
card data ever reaches Odoo. Revolut then notifies Odoo through a signed webhook,
and Odoo confirms the transaction and registers the payment.

Supported: hosted checkout, manual capture (full amount only), full and partial
refunds, sandbox and production environments.

This is the **Merchant API** — money coming in from a customer. Two other modules carry the Revolut
name and are entirely separate products with separate credentials: `legacy_accounting_helper` (the
**Business API**: bank statement import and reconciliation) and `hpc_revolut_payments` (contractor
payouts by CSV). How the three fit together, and where a card payment stops being automatic, is in
the Obsidian note `obsidian/Projects/Odoo-Revolut-Payment-Module/11-Revolut-Flows-End-to-End.md`.

## Main components

| File | Responsibility |
|---|---|
| `models/payment_provider.py` | The `revolut` provider: credentials, API host, the HTTP layer (`_revolut_make_request`), and the *Generate your webhook* button. |
| `models/payment_transaction.py` | The payment flow: the order payload, the redirection, capture / void / refund, and the verification and application of the order data. |
| `models/payment_transaction_reconcile.py` | The reconciliation cron and the alerts: what happens to a payment nobody told Odoo about. |
| `controllers/main.py` | Two public routes: the customer return route and the webhook route, including the HMAC signature check. |
| `const.py` | API version, hosts, supported currencies, payment method mapping, handled webhook events, state mapping, replay tolerance. |
| `views/payment_provider_views.xml` | The credentials page: the two secret fields, the gated webhook button, and the warnings that name a broken setup before it is used. |
| `views/payment_transaction_views.xml` | The *Cancel Revolut Order* button, shown only on a pending Revolut transaction. |
| `data/payment_provider_data.xml` | The provider record. |
| `data/payment_cron.xml` | The reconciliation cron, every 15 minutes. |
| `data/neutralize.sql` | Clears the credentials when a database is neutralized. |

## Business logic worth knowing

**The order is created late.** The Revolut order is created in
`_get_specific_rendering_values`, when the customer clicks *Pay now* — not when
the transaction is created. An order that is never paid simply expires on
Revolut's side.

**The order id is the handle.** It is stored in `provider_reference` immediately
after the order is created, because the customer is about to leave for the hosted
page where the payment happens outside of Odoo's sight.

**The state always comes from the API.** `_revolut_verify_and_apply` refetches
the order from Revolut unless the data came from a request Odoo itself made. A
webhook only says *that* something happened; the state Odoo acts on is never a
payload someone could have crafted.

**Everything goes through one door.** The webhook, the customer coming back from
the hosted page, the reconciliation cron and the capture / void / refund requests
all end up in `_revolut_verify_and_apply`. Anything that skips it changes money
without checking it.

**An order has to prove it is this transaction's order.** Before any state is
applied, `_revolut_check_order_matches` compares the order id against
`provider_reference`, the currency, and the amount **in minor units, as
integers** — the number Revolut actually charged, free of the rounding a float
comparison would have to tolerate. A mismatch changes nothing, alerts a human and
raises; a refund is compared on its own (positive) amount.

**A declined card does not leave the transaction pending.** Revolut keeps the
order `pending` after a decline so the customer can retry on the same page.
Reading the order state alone would have Odoo telling them the payment is being
processed while nothing was taken, so the last entry of `payments[]` decides:
`declined` or `failed` puts the transaction in error. A later successful attempt
on the same order still confirms it (`error → done` is allowed).

**An order that expires unpaid is a cancellation, not an error.** `ORDER_FAILED`
with an empty `payments[]` means nobody ever paid; the transaction is canceled so
the document stops waiting. With a failed attempt on it, it is an error.

**Nothing is lost when a webhook is not delivered.** Revolut retries a failed
delivery three times, ten minutes apart, and then drops it: a database that is
down for an hour never hears about those payments again. The cron
`_cron_revolut_reconcile_pending_transactions` asks the API itself every 15
minutes about transactions between 2 minutes and 7 days old that never reached a
final state, in batches of 100, committing each one on its own.

**The customer waiting on the status page is asked on their behalf.** Revolut
redirects the customer back as soon as the hosted page is done with them, which is
regularly *before* the order leaves `processing` — verified on 2026-08-27, when the
return route fetched an order five seconds after a successful 3DS payment and got
`processing` with `authorisation_passed` on the attempt. The transaction is then
correctly `pending`, and nothing revisits it until a webhook arrives or the cron
runs. `_get_post_processing_values` therefore refreshes it from the API: the status
page already polls every three seconds
(`payment/static/src/js/post_processing.js`), so the wait becomes about three
seconds instead of up to fifteen minutes. One API call per
`const.POLL_STATUS_MIN_INTERVAL_SECONDS` at most, every failure swallowed — this
runs while a customer is looking at the page, and a slow API must never replace
their payment status with a traceback. Post-processing is finalized in the same
call, because `poll_status` decides whether to run it *before* it reads these
values. **It is not a replacement for the webhook**: it only works while somebody
is watching.

**An abandoned checkout must not lock the invoice.** Odoo hides the portal *Pay
now* button of an invoice while a transaction of its own is pending
(`account.move._has_to_be_paid`), so a customer who opens the hosted page and
closes it cannot pay that invoice online any more. Revolut leaves such an order
`pending` indefinitely unless the order says otherwise — verified on 2026-08-24,
when an order created ten days earlier was still `pending` with an empty
`payments[]`. Every order therefore carries `expire_pending_after`
(`const.ORDER_EXPIRE_PENDING_AFTER`, one hour): the order fails on its own,
Revolut sends `ORDER_FAILED` with no payment on it, and the transaction is
canceled — which is the state that gives the button back. The window can only be
set when the order is created, never changed afterwards. For the orders created
before this, and for anyone who does not want to wait out the hour, the *Cancel
Revolut Order* button on a pending transaction does the same thing on demand,
through `_send_void_request` — the one place that calls the cancel endpoint.

**A payment that needs a human gets one.** An amount that does not match, or a
transaction still pending an hour later, schedules an activity for the accountant
set in *Payment Alerts Responsible* on the provider — on the invoice or order the
payment is for, or as a notification when there is no document. One alert per
transaction: the cron comes back every fifteen minutes, an alert repeated
ninety-six times a day is one nobody reads.

**`authorised` depends on the capture mode.** With automatic capture it means
"Revolut will capture on its own", so the transaction is only held *pending*;
confirming there would post a payment that may never settle. With manual capture
it maps to *authorized*. This is why `authorised` is absent from
`PAYMENT_STATUS_MAPPING`.

**A refund has an order of its own.** Revolut answers a refund with a new order
id, which is stored on the refund transaction. Matching therefore tries the order
id first and the reference only as a fallback — matching on the reference alone
would route refund events to the transaction being refunded. A completed refund
also triggers `payment.cron_post_process_payment_tx` explicitly, because nobody
is browsing the portal after a refund.

**Local base URLs are refused up front.** Revolut rejects the whole order — not
just the redirection — when the return URL host is `localhost` or an IP address.
`_revolut_get_checked_base_url` turns that into an actionable message at
configuration time instead of a bare *Bad Request* on the first real payment.

**Webhook signatures cover the raw bytes.** `_verify_notification_signature`
checks `v1.<timestamp>.<raw body>` against the stored signing secret, refuses
notifications older than `WEBHOOK_TIMESTAMP_TOLERANCE` (5 minutes), and accepts
any one of the comma-separated signatures in the header — which is what makes a
secret rotation survivable. A notification that cannot be matched or verified is
still acknowledged with a 200 when the failure is a `ValidationError`, so that
Revolut does not retry it forever; a failed signature check answers 403.

**The webhook button is re-runnable.** Revolut allows one webhook per URL, so
`action_revolut_create_webhook` updates an existing webhook on this database's
URL in place and rotates its signing secret instead of duplicating it. Rotating
is also what makes the button safe to press on a database copy: the copy gets a
secret of its own instead of silently sharing one.

## What happens after the transaction is done

The module's job ends at `state = 'done'`. What changes the *invoice* is stock Odoo, and it is worth
knowing because the last step of it is not automatic.

```
tx 'done' ──► _finalize_post_processing()      called by /payment/status/poll while the customer
    │                                          is on the status page, or by the cron
    │                                          payment.cron_post_process_payment_tx (10 min)
    ├──► invoice_ids.filtered(draft).action_post()
    └──► _create_payment()          account_payment/models/payment_transaction.py:130
           account.payment on provider.journal_id, posted, its counterpart on
           **Outstanding Receipts**, then reconciled against the invoice receivable
                │
                ▼
         payment_state:  residual 0 and is_matched False  →  'in_payment'
                         residual 0 and is_matched True   →  'paid'
```

`account.payment.is_matched` means *"reconciled with a bank statement line"*. Straight after a card
payment it is False, so **the expected state of a freshly paid invoice is `in_payment` with residual
0.00, not `paid`** — on any database where `account_accountant` is installed, since it overrides
`_get_invoice_in_payment_state()` to return `'in_payment'` (`account_accountant/models/account_move.py:63`).
It becomes `paid` when the Revolut merchant settlement is imported as a bank statement line and
matched against the payment's Outstanding Receipts line. Nothing in this module, and nothing in
`legacy_accounting_helper`, does that — see the Obsidian note `obsidian/Projects/Odoo-Revolut-Payment-Module/11-Revolut-Flows-End-to-End.md` §7.

Two traps in that tail:

* **`payment.cron_post_process_payment_tx` ships inactive** (`active="False"` in
  `payment/data/payment_cron.xml`) and is meant to be woken by `_trigger()`. But
  `ir_cron._trigger_list` (`base/models/ir_cron.py:514`) silently drops a trigger aimed at an
  inactive cron. On a neutralized copy — `base/data/neutralize.sql` disables every cron but
  `base.autovacuum_job` — a transaction reaches `done`, `payment_id` stays `False` and the invoice
  stays `not_paid`, unless somebody is sitting on the portal status page. Check that cron first when
  a `done` transaction has posted no payment.
* **The refund path depends on that same cron.** `_revolut_apply_order_state` triggers it explicitly
  because nobody browses the portal after a refund; if it is inactive, the trigger is a no-op.

## The Credentials page (v17.0.2.2.0)

The page is **quiet by default and loud only when something will not work**. It
is built from stock idioms on purpose — a conditional `alert alert-warning`
(`payment_adyen`, `payment_razorpay_oauth`), a field-plus-button `o_row` with
the button gated on its prerequisites (`payment_stripe`), and `text-muted`
lines. No custom card and no SCSS: `web_ribbon` and the `state` radio already
announce the environment, and a bespoke panel would only drift from the design
system on upgrades. For the record, no stock payment provider ships a
`compute=` on `payment.provider` at all.

What it now says before the user can get it wrong:

* **No key** — and that `State` picks the environment, since sandbox and
  production have separate keys and nothing in a key tells them apart.
* **No public HTTPS** — showing the URL this database actually resolves to.
  `action_revolut_create_webhook` refuses such a URL, so the button is hidden
  rather than offered and then raising.
* **Webhook not registered** — with what that costs: nothing tells Odoo the
  payment succeeded except the reconciliation cron.
* **Alerts responsible empty** — that the fallback is the first accountant of
  the company.
* **Currencies** — next to `available_currency_ids`, that UAH, BGN, BRL, CNY and
  RUB are not settled by Revolut. That list is filled in automatically from
  `_get_supported_currencies()`, and `_get_compatible_providers` hides a
  provider whose currency list excludes the document currency: an invoice in
  UAH simply does not offer Revolut, with no error anywhere. The line is the
  only place that says so.

Two computed, non-stored fields back this: `revolut_webhook_url` and
`revolut_webhook_url_is_https`. They exist because a view expression can
neither join a base URL to a route nor inspect a URL scheme. **Neither makes a
network call** — a compute runs on every form open, and `test_webhook_url_
compute_makes_no_request` fails the build if one ever does.

Re-registering rotates the signing secret, so the second press is a separate
*Re-generate* button behind a `confirm=`.

## Constraints

- **Capture is full-only** (`support_manual_capture = 'full_only'`). A partial
  capture would leave Odoo tracking child transactions that Revolut does not
  model the same way.
- **Refunds are partial** (`support_refund = 'partial'`): any amount up to the
  captured total, in as many steps as needed.
- **An order expires after `const.ORDER_EXPIRE_PENDING_AFTER`.** The API accepts
  `PT1M` to `PT720H`. The order is created when the customer clicks *Pay now*, not
  when the invoice is sent, so the window covers one sitting at the checkout page.
- **The API version is pinned** (`const.API_VERSION`). Revolut rejects a request
  without the `Revolut-Api-Version` header, and the payload shape depends on it.
- **Sandbox vs production is decided by the provider `state`**, not by the key:
  the two environments are separate installations and nothing in the key itself
  tells them apart. A provider in `test` state must hold a sandbox key.
- **The webhook URL must be public HTTPS.** Set `web.base.url` to the public
  address of the database before pressing the webhook button.
- Both secrets are restricted to `base.group_system`.
- **Alerts need a responsible.** Left empty, `revolut_alert_user_id` falls back to
  the first accounting manager of the company and says so in the log — a working
  fallback, not a working setup.
- **A reconciliation run is bounded in time** by
  `const.CRON_TIME_BUDGET_SECONDS` (120 s) as well as by `POLL_BATCH_SIZE`. It talks
  to an API with a 60-second timeout up to a hundred times; without a budget one
  unreachable host would hold a cron worker — and every cron queued behind it — for
  the better part of an hour. Transactions are polled oldest first, so what is
  postponed is the newest of the batch and is reached first next run.
- **The cron commits.** It walks up to a hundred transactions and talks to an API
  in between, so it keeps what it has reconciled rather than risking the lot on
  the last one. Commits are skipped while testing, the same guard as
  `account.move._can_commit`.

## Diagnosing a problem in production

Every branch that refuses, fails or falls back logs *why*, *which transaction*,
and *what to do about it* — the logger names are
`odoo.addons.payment_revolut.{controllers.main,models.payment_provider,models.payment_transaction}`.

| Symptom | What the log says |
|---|---|
| Payments stay unconfirmed | `Refused the notification for transaction <ref>: …` — one line per reason: no secret stored, missing header, unreadable timestamp, outside the replay window, or no matching signature. Each names the provider and, where relevant, points at the *Generate your webhook* button. |
| Nothing happens at all | `The event <X> is not handled by this module` (webhook subscribed to the wrong events), or `No transaction found matching the order …` (often another database sharing the merchant account). |
| A payment fails at checkout | `Revolut refused the <METHOD> request at <url> with HTTP <code>` followed by what was sent and what came back. |
| The transaction is in error | `Received the order <id> … in the unknown state '<state>'` — the Merchant API gained a state and `const.PAYMENT_STATUS_MAPPING` has to be updated. |
| The payment method looks wrong | `Revolut reported … '<code>', which matches no active payment method in Odoo` — activate it, or map it in `const.PAYMENT_METHODS_MAPPING`. |

Secrets are never logged. The signature failure logs the timestamp and the body
*length* — enough to reproduce the signed payload, not enough to forge one.

## Tests

One file per layer, so that the name of the failing file already says what broke:

```
tests/
├── common.py                     # fixtures, the fake API response, the webhook signing mixin
├── test_revolut.py               # the order sent when the customer clicks "Pay now"
├── test_revolut_states.py        # the state that comes back, and which transaction it is about
├── test_revolut_status_page.py   # the refresh done for a customer waiting on the status page
├── test_revolut_operations.py    # capture / void / refund
├── test_revolut_provider.py      # provider configuration and webhook management
├── test_revolut_http.py          # the HTTP layer: headers, URLs, API errors, network failures
├── test_revolut_webhook.py       # the controller: signature verification and the return route
├── test_revolut_notification.py  # refused order data and the payment method actually used
├── test_revolut_verification.py  # what an order must prove before it decides anything
└── test_revolut_reconcile.py     # the cron that catches what the webhook never delivered
```

Two levels of mocking are used. Business logic patches
`PaymentProvider._revolut_make_request` (`common.REQUEST_PATH`), as the core Odoo
payment providers do. `test_revolut_http.py` goes one level lower and patches
`requests.request` (`common.HTTP_REQUEST_PATH`) so that the error handling of the
HTTP layer itself is actually executed; `_revolut_response()` builds a real
`requests.Response` so `raise_for_status`, `json()` and `text` behave exactly as
in production. **No test may reach the network** — the notifications that must be
refused before any API call assert that the request was never made.

### Failure messages

A failing test has to be readable by whoever did not write it. Every assertion
carries a sentence naming **the rule that is broken and what it costs**, not a
restatement of the code, plus the context needed to tell a broken rule from a
broken test. `common.py` provides the helpers that render it:

| Helper | Shows on failure |
|---|---|
| `assertTxState(tx, state, why)` | reference, operation, amount, expected vs actual state, state message, order id |
| `assertApiCalls(api, calls, why)` | the expected and the actual request sequence, one per line |
| `assertNoApiCall(api, why)` | the requests that were made nonetheless |
| `assertPayloadValue(payload, key, expected, why)` | the key, expected vs actual, and the whole payload |
| `assertRefused` / `assertAcknowledged(response, why)` | HTTP status, the body posted, the timestamp, how many signatures were sent |

For example, a signature check that stops matching fails with:

```
AssertionError: 403 != 200 : A correctly signed notification must be accepted; a 403
here means Odoo and Revolut no longer compute the signature the same way, and no
payment can be confirmed.
    expected HTTP 200, got HTTP 403
    body sent:  {"event": "ORDER_COMPLETED", "order_id": "6a7f39f4-…", …}
    timestamp:  1786748751763
    signatures: 1 sent
```

Run them on a dedicated database:

```bash
odoo-bin -d <test_db> -u payment_revolut --test-enable \
         --test-tags /payment_revolut --stop-after-init
```

A single layer can be run on its own, which is the point of the split:

```bash
--test-tags /payment_revolut:RevolutWebhookTest
```

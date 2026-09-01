# The version of the Merchant API this module is written against. Revolut
# rejects any request without this header ("Missing Revolut-Api-Version"), and
# the payload shape depends on it, so it is pinned rather than derived.
API_VERSION = '2024-09-01'

# The API hosts. Sandbox and production are separate installations with
# separate API keys; the provider `state` selects between them.
API_URLS = {
    'sandbox': 'https://sandbox-merchant.revolut.com',
    'production': 'https://merchant.revolut.com',
}

# How long Revolut keeps an unpaid order alive before failing it, as an ISO 8601 duration. The
# API accepts `PT1M` to `PT720H`, and only at creation time: the window of an existing order can
# never be changed.
#
# The order is created when the customer clicks "Pay now", not when the invoice is sent, so this
# covers a single sitting at the checkout page — not the time the customer takes to decide. An
# hour is far beyond entering a card and passing 3DS.
#
# It matters beyond tidiness: `account.move._has_to_be_paid` hides the portal "Pay now" button
# while a transaction is pending, so a customer who opens the checkout page and closes it locks
# themselves out of paying that invoice online until the order dies and Odoo hears about it.
# Without this field, Revolut leaves the order pending indefinitely — verified on 2026-08-24, when
# an order created on 2026-08-14 was still `pending` with an empty `payments[]`.
ORDER_EXPIRE_PENDING_AFTER = 'PT1H'

# The currencies accepted by the Merchant API. Read from the API itself: an
# order with an unsupported currency is rejected with the full list in the
# error message. Notably absent: UAH, BGN, BRL, CNY, RUB.
SUPPORTED_CURRENCIES = [
    'AED', 'AUD', 'CAD', 'CHF', 'CLP', 'COP', 'CZK', 'DKK', 'EUR', 'GBP',
    'HKD', 'HUF', 'ILS', 'INR', 'ISK', 'JPY', 'KRW', 'MXN', 'NOK', 'NZD',
    'PHP', 'PLN', 'QAR', 'RON', 'RSD', 'SAR', 'SEK', 'SGD', 'THB', 'TRY',
    'USD', 'ZAR',
]

# The codes of the payment methods to activate when Revolut is activated.
DEFAULT_PAYMENT_METHODS_CODES = [
    # Primary payment methods.
    'card',
    # Brand payment methods.
    'visa',
    'mastercard',
    'maestro',
    'amex',
]

# Mapping of Odoo payment method codes to the payment method and card brand
# names Revolut reports on a paid order. Only the codes that actually differ
# are listed; everything else (card, visa, mastercard, maestro) is spelled the
# same on both sides and resolves by identity.
PAYMENT_METHODS_MAPPING = {
    'revolut_pay': 'pay_with_revolut',
}

# The webhook events this module subscribes to. Revolut rejects unknown event
# names, and these are the order-level events of the payment flow; the
# PAYOUT_* events describe settlements to the merchant's own account and are
# not about a single transaction.
HANDLED_WEBHOOK_EVENTS = [
    'ORDER_COMPLETED',
    'ORDER_AUTHORISED',
    'ORDER_CANCELLED',
    # Sent when the order itself reaches a dead end: it expired before anyone paid, or the last
    # attempt failed for good. Without it, an abandoned order would leave the transaction pending
    # forever, because no other event is ever sent for it.
    'ORDER_FAILED',
    'ORDER_PAYMENT_DECLINED',
    'ORDER_PAYMENT_FAILED',
]

# Mapping of Revolut order states to Odoo payment transaction states.
# `authorised` is deliberately absent: it means "captured or awaiting capture"
# depending on the capture mode, so it is resolved in the transaction.
PAYMENT_STATUS_MAPPING = {
    'pending': ('pending', 'processing'),
    'done': ('completed',),
    'cancel': ('cancelled',),
    'error': ('failed',),
}

# The states of a payment attempt that mean the customer's money did not move. The order stays
# `pending` afterwards, because Revolut lets the customer try again on the same checkout page, so
# these states are the only thing that tells a failed attempt from one that has not happened yet.
FAILED_PAYMENT_STATES = ('declined', 'failed')

# How old, in seconds, a webhook notification may be before it is refused.
# Revolut recommends a 5-minute tolerance to mitigate replay attacks.
WEBHOOK_TIMESTAMP_TOLERANCE = 300

# The reconciliation cron. Revolut retries a failed webhook delivery three times, ten minutes
# apart, and then gives up for good: a database that is down for an hour never hears about those
# payments again. The cron asks the API itself, and is the only thing that makes a payment
# impossible to lose.
#
# A transaction is polled once it is old enough that the customer had time to reach the hosted page
# (POLL_MIN_AGE), and until its order can no longer change on Revolut's side (POLL_MAX_AGE, which
# matches the longest order lifetime the provider allows).
POLL_MIN_AGE_MINUTES = 2
POLL_MAX_AGE_DAYS = 7
POLL_BATCH_SIZE = 100

# How long a transaction may stay pending before a human is told about it. Legitimately pending
# payments (bank redirects, slow issuers) settle in minutes; an hour means something is wrong.
STUCK_ALERT_DELAY_HOURS = 1

# How often, at most, the payment status page may ask Revolut about one transaction. The page
# polls Odoo every three seconds while the customer waits
# (`payment/static/src/js/post_processing.js`), and answering each poll with an API call would
# turn one payment into a dozen of them. Five seconds keeps the wait imperceptible while making
# the calls roughly one per poll at worst.
POLL_STATUS_MIN_INTERVAL_SECONDS = 5

# How long one reconciliation run may spend before it stops and leaves the rest to the next one.
# The run talks to an API with a 60-second timeout, up to POLL_BATCH_SIZE times: without a budget
# a single unreachable host could hold the cron worker — and every other cron queued behind it —
# for the better part of an hour. Transactions are polled oldest first, so what is postponed is
# always the most recently created.
CRON_TIME_BUDGET_SECONDS = 120

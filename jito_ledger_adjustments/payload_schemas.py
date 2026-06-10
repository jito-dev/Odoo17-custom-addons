# -*- coding: utf-8 -*-

"""Per-kind schema registry for jito.ledger.trace.source_payload.

Per HLD Decision #6: hybrid `source_payload_kind` Selection +
free-form JSON, with a Python registry per kind. Used when a trace
row's source is **not** a stock account.move.line (the soft FK is
NULL and the line points at a non-Odoo source like a USDC tx).

Kinds shipped in v1:
  * `crypto_tx` — for sca.transaction (simple_crypto_accounting)
  * `external_receipt` — out-of-band receipts / scanned docs
  * `manual_entry` — pure management opinion, no external source

Downstream modules can register additional kinds via Odoo's
`selection_add` pattern on jito.ledger.trace.source_payload_kind and
extend this registry as needed.

Unknown kinds degrade gracefully in reports: rendered as raw JSON, no
crash (per Decision #6).
"""

# kind → required keys (informative; validation is light by design).
SCHEMAS = {
    'crypto_tx': {
        'tx_hash', 'token', 'amount_decimal', 'direction',
        'block_number', 'wallet_address',
    },
    'external_receipt': {
        'document_ref', 'amount', 'currency', 'date',
    },
    'manual_entry': {
        'memo', 'author',
    },
}


def is_known_kind(kind):
    return kind in SCHEMAS


def expected_keys(kind):
    return SCHEMAS.get(kind, set())

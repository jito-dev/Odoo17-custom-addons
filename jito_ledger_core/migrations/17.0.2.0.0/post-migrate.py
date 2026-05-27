# -*- coding: utf-8 -*-

"""Post-migration for 17.0.2.0.0.

Promotes every existing ``jito.ledger.journal.rel`` row into a new
``jito.ledger.journal`` record, copying ``name``/``code`` from the
linked stock ``account.journal`` and carrying ``default_account_id``
across. Each new row records the legacy ``account.journal.id`` in
``source_account_journal_id`` so downstream module migrations
(jito_ledger_nl, jito_ledger_adjustments, simple_crypto_accounting)
can translate old FKs to new ones via a single JOIN.

Idempotent: rows whose stock journal is already promoted (matched on
``source_account_journal_id``) are skipped.
"""

import logging

_logger = logging.getLogger(__name__)


def _flatten(value):
    """Return a plain string from a possibly-translatable column value.

    Odoo 17 stores ``translate=True`` Char fields as a JSONB blob like
    ``{"en_US": "Customer Invoices"}``; raw SQL fetches return a dict.
    Prefer the English value, then any non-empty entry, then ''.
    """
    if isinstance(value, dict):
        return value.get('en_US') or next(
            (v for v in value.values() if v), ''
        )
    return value or ''


def migrate(cr, version):
    # Find rel rows that haven't been promoted yet.
    cr.execute("""
        SELECT rel.id,
               rel.ledger_id,
               rel.journal_id,
               rel.default_account_id,
               aj.name,
               aj.code,
               aj.currency_id
          FROM jito_ledger_journal_rel rel
          JOIN account_journal aj
            ON aj.id = rel.journal_id
     LEFT JOIN jito_ledger_journal jlj
            ON jlj.source_account_journal_id = rel.journal_id
         WHERE jlj.id IS NULL
    """)
    pending = cr.fetchall()
    if not pending:
        _logger.info(
            "jito_ledger_core 17.0.2.0.0: no rel rows to promote — "
            "all stock journals already mapped."
        )
        return

    inserted = 0
    for rel_id, ledger_id, journal_id, default_account_id, jname, jcode, jcurrency_id in pending:
        # Translatable fields (`name`) come back as dicts via raw SQL —
        # flatten to a plain string before INSERT.
        jname = _flatten(jname)
        jcode = _flatten(jcode)
        # Resolve a unique code within the company. The stock journal's
        # code is usually fine; on the off-chance two stock journals
        # share a code+company (rare), fall back to suffixing.
        code = jcode or ('MJ%d' % journal_id)
        cr.execute("""
            SELECT 1
              FROM jito_ledger_journal jlj
              JOIN jito_ledger l ON l.id = jlj.ledger_id
              JOIN jito_ledger l2 ON l2.id = %s
             WHERE jlj.code = %s
               AND l.company_id = l2.company_id
             LIMIT 1
        """, (ledger_id, code))
        if cr.fetchone():
            code = '%s-%d' % (code, journal_id)
        cr.execute("""
            INSERT INTO jito_ledger_journal (
                name, code, ledger_id, currency_id,
                default_account_id, source_account_journal_id,
                active, sequence,
                create_uid, create_date, write_uid, write_date
            ) VALUES (
                %s, %s, %s, %s,
                %s, %s,
                TRUE, 10,
                1, NOW(), 1, NOW()
            )
        """, (
            jname or code, code, ledger_id, jcurrency_id,
            default_account_id, journal_id,
        ))
        inserted += 1

    _logger.info(
        "jito_ledger_core 17.0.2.0.0: promoted %d account.journal rel "
        "rows into jito.ledger.journal records.",
        inserted,
    )

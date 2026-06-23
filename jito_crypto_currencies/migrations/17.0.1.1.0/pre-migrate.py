# -*- coding: utf-8 -*-
"""Bind pre-existing currencies (USDC/USDT/DAI/BTC/ETH) to our
``jito_crypto_currencies`` xmlids if the binding is missing.

17.0.1.1.0 introduces a new TRX currency record. On upgrade, Odoo
re-evaluates the entire ``data/res_currency.xml``. For currencies
whose xmlids are already bound to a row in ``ir_model_data``, the
``noupdate="1"`` semantic correctly skips them. But if the dev
database was set up before this module ever wrote its xmlids (e.g.
USDC was created manually or by another module), the upgrade tries
to CREATE a fresh USDC row and trips the UNIQUE(name) constraint on
``res_currency``.

This pre-migrate scans for existing currencies by ``name`` and
inserts the missing ``ir_model_data`` rows so the framework treats
them as already-loaded and skips the create.
"""


def migrate(cr, version):
    bindings = [
        ('USDC', 'currency_usdc'),
        ('USDT', 'currency_usdt'),
        ('DAI', 'currency_dai'),
        ('BTC', 'currency_btc'),
        ('ETH', 'currency_eth'),
        # TRX is new in 17.0.1.1.0; safe to also bind if any
        # pre-existing TRX row has slipped in.
        ('TRX', 'currency_trx'),
    ]
    for name, xmlid in bindings:
        cr.execute(
            "SELECT id FROM res_currency WHERE name = %s LIMIT 1",
            (name,),
        )
        row = cr.fetchone()
        if not row:
            continue
        currency_id = row[0]
        cr.execute(
            "SELECT id FROM ir_model_data "
            " WHERE module = 'jito_crypto_currencies' "
            "   AND name = %s",
            (xmlid,),
        )
        if cr.fetchone():
            continue  # already bound
        cr.execute(
            "INSERT INTO ir_model_data "
            "  (module, name, model, res_id, noupdate) "
            "VALUES (%s, %s, %s, %s, %s)",
            ('jito_crypto_currencies', xmlid,
             'res.currency', currency_id, True),
        )

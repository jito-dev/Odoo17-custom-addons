{
    'name': 'Jito Crypto Currencies',
    'version': '17.0.1.0.0',
    'category': 'Accounting/Currencies',
    'summary': 'Allows cryptocurrencies (USDC, USDT, DAI, BTC, ETH, …) as '
               'first-class res.currency records by lifting the 3-char '
               'name limit, and seeds the common stablecoins + majors. '
               'Manual rate management via the standard Odoo Currencies UI.',
    'description': """
Jito Crypto Currencies
======================

Purpose
-------
Stock Odoo's ``res.currency.name`` is declared with ``size=3`` to
enforce ISO 4217 codes (USD/EUR/GBP/…). That makes it impossible to
register USDC, USDT, MATIC, or any other crypto with a longer ticker.

This module lifts the constraint and ships a curated set of seeded
crypto currencies, so every other module (invoicing, accounting,
management ledger, partner ledger, etc.) automatically gains crypto
support without further code changes.

What it does
------------
* ``_inherit`` ``res.currency`` to override ``name`` with ``size=10``.
* Adds ``is_crypto`` (Boolean) on ``res.currency`` for filtering /
  reporting separation.
* Seeds (with ``noupdate=1`` so user edits survive upgrades):
    - **Stablecoins**: USDC, USDT, DAI (6 decimals each)
    - **Majors**: BTC (8 decimals), ETH (8 decimals — display cap;
      on-chain wei has 18 but practical accounting precision is 8)
* Currency form: adds an "Is Crypto" checkbox.
* Currency search: filters "Crypto" / "Fiat".

Rate management
---------------
Manual entry via the standard Odoo Currencies UI:
**Accounting → Configuration → Currencies → <crypto> → Rates** tab.
A scheduled price feeder (CoinGecko / Tronscan) is a planned follow-up
and would live in the same module so the rate plumbing stays
co-located with the currency definitions.

How downstream code uses this
-----------------------------
Once a crypto currency is a real ``res.currency`` record with rates:

* The Management Ledger's per-line ``currency_id`` accepts it directly.
* ``simple_crypto_accounting`` (17.0.6.0.0+) links its ``sca.token`` /
  ``sca.token.preset`` rows to these currency records, so injected
  crypto transactions land in jito.ledger.move with the right
  ``currency_id``.
* The Trial Balance and Partner Ledger reports' ``_build_rate_map``
  helper translates crypto amounts to company currency at report time
  exactly like it does for any fiat currency — no separate code path.
""",
    'author': 'JITO LTD',
    'website': 'https://jito.dev',
    'license': 'LGPL-3',
    'depends': ['base'],
    'data': [
        'data/res_currency.xml',
        'views/res_currency_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}

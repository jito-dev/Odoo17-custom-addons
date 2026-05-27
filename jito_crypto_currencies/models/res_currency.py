# -*- coding: utf-8 -*-

from odoo import api, fields, models


class ResCurrency(models.Model):
    """Inherit res.currency to:

      * Lift the ``size=3`` enforced by ISO 4217. Cryptos commonly use
        4-character tickers (USDC, USDT, USDP, DASH, MATIC, LINK) and
        the field needs room for them. We allow up to 10 chars — more
        than any real-world ticker without risking unbounded width
        problems in stock list views.
      * Add an ``is_crypto`` boolean for filtering / reporting
        separation between fiat and crypto entries.

    No business behaviour changes for existing fiat currencies —
    ``is_crypto`` defaults to ``False`` and the ``size`` change is
    strictly additive (any 3-char ISO code still fits).
    """

    _inherit = 'res.currency'

    # Redeclare `name` with a larger size limit. Other attributes
    # (required, translate, etc.) inherit from the stock declaration.
    name = fields.Char(
        size=10,
        help='Currency code. Standard fiat uses ISO 4217 (3 chars); '
             'crypto tickers may be longer (USDC, USDT, MATIC, …).',
    )
    is_crypto = fields.Boolean(
        string='Is Crypto',
        default=False,
        help='Mark this currency as a cryptocurrency. Reports and '
             'filters use the flag to separate from fiat. Set on '
             'install for the seeded crypto records; user-editable.',
    )

# -*- coding: utf-8 -*-

from odoo import fields, models


class SCAPriceCandle(models.Model):
    """Cached crypto price candle from Binance Klines (17.0.9.0.0).

    One row per (currency, timestamp, interval). Source-of-truth for
    USD pricing during management-ledger injection: when an
    ``sca.transaction`` is injected, ``sca.price.feed`` resolves the
    block timestamp to a candle here, then passes
    ``close_usd × value_decimal`` as the explicit ``balance`` on the
    generated ``jito.ledger.move.line`` (per the 17.0.10.0.0 ADR).

    Cache lives forever — historical candle close prices don't
    change. Re-syncs / re-injections become O(1) lookups.
    """

    _name = 'sca.price.candle'
    _description = 'Crypto Price Candle (Binance Klines cache)'
    _order = 'currency_id, timestamp'
    _rec_name = 'timestamp'

    currency_id = fields.Many2one(
        comodel_name='res.currency',
        required=True,
        ondelete='cascade',
        index=True,
    )
    timestamp = fields.Datetime(
        required=True,
        index=True,
        help="Candle open time, UTC. Matches the Binance kline's openTime.",
    )
    close_usd = fields.Float(
        string='Close (USD)',
        required=True,
        digits=(16, 8),
        help="Candle close price in USD (via USDT pair, treating "
             "USDT ≈ USD).",
    )
    interval_code = fields.Selection(
        selection=[
            ('1m', '1 minute'),
            ('1h', '1 hour'),
            ('1d', '1 day'),
        ],
        required=True,
        help="Granularity of the candle. The fetch service picks the "
             "coarsest interval that still gives sub-tolerance "
             "accuracy for a given batch of transaction timestamps.",
    )
    source = fields.Selection(
        selection=[
            ('binance_klines', 'Binance Klines'),
            ('manual', 'Manual override'),
        ],
        default='binance_klines',
        required=True,
    )

    _sql_constraints = [
        (
            'uniq_currency_ts_interval',
            'UNIQUE(currency_id, timestamp, interval_code)',
            'Already cached a candle for this currency at this '
            'timestamp and interval.',
        ),
    ]

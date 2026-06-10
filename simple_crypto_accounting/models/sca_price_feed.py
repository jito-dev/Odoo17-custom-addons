# -*- coding: utf-8 -*-

import json
import logging
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta

from odoo import api, models


_logger = logging.getLogger(__name__)


class SCAPriceFeed(models.AbstractModel):
    """Binance Klines price fetcher with smart granularity selection
    and a per-currency cache (17.0.9.0.0).

    Architecture: for a batch of ``(currency, timestamp)`` lookups,
    determine the **coarsest** Binance interval (``1m`` / ``1h`` /
    ``1d``) whose 1000-candle page still covers the full
    ``max(ts) - min(ts)`` span — then do at most a handful of HTTP
    calls (often just 1 per token), cache every returned candle in
    ``sca.price.candle``, and map each lookup back to the nearest
    cached candle.

    Stable coins (USDT / USDC / etc.) short-circuit to 1.0 USD with
    no API call.
    """

    _name = 'sca.price.feed'
    _description = 'Binance Klines price fetcher'

    # Native tokens & well-known symbols mapped directly to their
    # Binance USDT-paired symbol. Token contract presets carry their
    # own ``binance_symbol`` field; this table covers the chain-native
    # tokens that don't have a preset (TRX, ETH, BTC, BNB).
    NATIVE_SYMBOLS = {
        'TRX': 'TRXUSDT',
        'ETH': 'ETHUSDT',
        'BTC': 'BTCUSDT',
        'BNB': 'BNBUSDT',
    }
    # Stable coins treated as 1:1 USD (no API call needed).
    STABLE_COINS = {'USDT', 'USDC', 'USD', 'BUSD', 'DAI', 'TUSD', 'FDUSD'}

    BINANCE_KLINES_URL = 'https://api.binance.com/api/v3/klines'
    MAX_CANDLES_PER_REQUEST = 1000
    HTTP_TIMEOUT = 20  # seconds

    # Granularity ladder. The fetcher picks the coarsest interval
    # whose ``max_candles_per_request × interval_seconds`` covers
    # the requested timestamp span — so a single request typically
    # suffices.
    INTERVAL_SECONDS = {
        '1m': 60,
        '1h': 3600,
        '1d': 86400,
    }
    INTERVAL_THRESHOLDS = [
        # (max span seconds, interval_code)
        (16 * 3600,         '1m'),   # ≤ 16h → 1-minute candles
        (41 * 86400,        '1h'),   # ≤ 41d → 1-hour candles
        (1000 * 86400,      '1d'),   # ≤ 2.7y → 1-day candles
    ]

    @api.model
    def _get_binance_symbol(self, currency):
        """Map an ``res.currency`` to a Binance USDT-paired symbol,
        or to ``None`` to signal "treat as 1:1 USD".

        Resolution order:
          1. Stable coins → None (1:1 USD).
          2. Hardcoded native tokens (TRX/ETH/BTC/BNB).
          3. ``sca.token.preset.binance_symbol`` lookup.
          4. None (unknown — caller's fallback handles it).
        """
        if not currency or not currency.name:
            return None
        name = currency.name.upper()
        if name in self.STABLE_COINS:
            return None
        if name in self.NATIVE_SYMBOLS:
            return self.NATIVE_SYMBOLS[name]
        preset = self.env['sca.token.preset'].sudo().search([
            ('currency_id', '=', currency.id),
            ('binance_symbol', '!=', False),
        ], limit=1)
        return preset.binance_symbol or None

    @api.model
    def _is_stable(self, currency):
        return bool(
            currency
            and currency.name
            and currency.name.upper() in self.STABLE_COINS
        )

    @api.model
    def fetch_prices(self, requests):
        """Resolve USD prices for a batch of ``(currency_id, datetime)``
        lookups.

        Args:
            requests: iterable of ``(currency_id: int, ts: datetime)``.

        Returns:
            dict ``{(currency_id, ts_normalized): close_usd or None}``.
            ``None`` means no price was resolvable (no Binance symbol
            mapping and not a stable coin); caller decides whether to
            skip or default.
        """
        by_currency = defaultdict(set)
        for currency_id, ts in requests:
            if not currency_id or not ts:
                continue
            ts_norm = ts.replace(microsecond=0)
            if ts_norm.tzinfo is not None:
                ts_norm = ts_norm.replace(tzinfo=None)
            by_currency[currency_id].add(ts_norm)

        result = {}
        for currency_id, ts_set in by_currency.items():
            currency = self.env['res.currency'].sudo().browse(currency_id)
            ts_list = sorted(ts_set)
            if self._is_stable(currency):
                for ts in ts_list:
                    result[(currency_id, ts)] = 1.0
                continue
            symbol = self._get_binance_symbol(currency)
            if not symbol:
                for ts in ts_list:
                    result[(currency_id, ts)] = None
                continue
            self._fetch_into_cache(currency, symbol, ts_list)
            for ts in ts_list:
                result[(currency_id, ts)] = self._lookup_cached(currency, ts)
        return result

    # ---- internal --------------------------------------------------------

    @api.model
    def _pick_interval(self, span_seconds):
        """Pick the coarsest interval whose 1000-candle page still
        covers the given span.
        """
        for threshold, code in self.INTERVAL_THRESHOLDS:
            if span_seconds <= threshold:
                return code
        return '1d'  # very long span → still 1d, paginate if needed

    @api.model
    def _fetch_into_cache(self, currency, symbol, ts_list):
        """Fetch Binance candles covering the span ``[ts_list[0],
        ts_list[-1]]`` at the chosen interval, write into
        ``sca.price.candle``. Skips ranges already fully cached.
        """
        if not ts_list:
            return
        span = (ts_list[-1] - ts_list[0]).total_seconds()
        interval = self._pick_interval(span)
        interval_sec = self.INTERVAL_SECONDS[interval]

        # Round the requested span to whole candle boundaries (open
        # times are aligned to integer seconds-since-epoch multiples
        # of interval_sec). Add one extra candle on each side so the
        # nearest-match lookup always has bracketing data.
        first_ts = int(ts_list[0].timestamp())
        last_ts = int(ts_list[-1].timestamp())
        start_ms = ((first_ts // interval_sec) - 1) * interval_sec * 1000
        end_ms = ((last_ts // interval_sec) + 2) * interval_sec * 1000

        Candle = self.env['sca.price.candle'].sudo()
        # Skip API call entirely if all needed candles are cached.
        existing_ts = set(Candle.search([
            ('currency_id', '=', currency.id),
            ('interval_code', '=', interval),
            ('timestamp', '>=', datetime.utcfromtimestamp(start_ms // 1000)),
            ('timestamp', '<', datetime.utcfromtimestamp(end_ms // 1000)),
        ]).mapped(lambda c: c.timestamp.replace(tzinfo=None)))

        cursor_ms = start_ms
        new_candle_vals = []
        while cursor_ms < end_ms:
            chunk_end_ms = min(
                end_ms,
                cursor_ms + self.MAX_CANDLES_PER_REQUEST * interval_sec * 1000,
            )
            url = (
                '%s?symbol=%s&interval=%s&startTime=%d&endTime=%d&limit=%d'
                % (
                    self.BINANCE_KLINES_URL, symbol, interval,
                    cursor_ms, chunk_end_ms, self.MAX_CANDLES_PER_REQUEST,
                )
            )
            try:
                response = self._http_get_json(url)
            except Exception as exc:
                _logger.warning(
                    "Binance fetch failed for %s @ %s [%s, %s]: %s",
                    symbol, interval, cursor_ms, chunk_end_ms, exc,
                )
                break
            if not response:
                break
            last_open_ms = None
            for candle in response:
                # Binance kline shape:
                # [openTime, open, high, low, close, volume, closeTime, ...]
                open_ms = candle[0]
                last_open_ms = open_ms
                open_time = datetime.utcfromtimestamp(open_ms // 1000)
                if open_time in existing_ts:
                    continue
                try:
                    close_price = float(candle[4])
                except (TypeError, ValueError):
                    continue
                new_candle_vals.append({
                    'currency_id': currency.id,
                    'timestamp': open_time,
                    'close_usd': close_price,
                    'interval_code': interval,
                    'source': 'binance_klines',
                })
                existing_ts.add(open_time)
            # If Binance returned fewer than the max, we're done.
            if len(response) < self.MAX_CANDLES_PER_REQUEST or last_open_ms is None:
                break
            cursor_ms = last_open_ms + interval_sec * 1000

        if new_candle_vals:
            Candle.create(new_candle_vals)

    @api.model
    def _lookup_cached(self, currency, ts):
        """Find the nearest cached candle for ``(currency, ts)``.

        Tries finer intervals first; tolerance for "nearest" is one
        candle-width either side of ``ts``. Returns ``close_usd`` or
        ``None`` when no candle is close enough.
        """
        Candle = self.env['sca.price.candle'].sudo()
        for interval in ('1m', '1h', '1d'):
            tol = self.INTERVAL_SECONDS[interval]
            lo = ts - timedelta(seconds=tol)
            hi = ts + timedelta(seconds=tol)
            candidates = Candle.search([
                ('currency_id', '=', currency.id),
                ('interval_code', '=', interval),
                ('timestamp', '>=', lo),
                ('timestamp', '<=', hi),
            ], limit=10)
            if not candidates:
                continue
            best = min(
                candidates,
                key=lambda c: abs((c.timestamp - ts).total_seconds()),
            )
            return best.close_usd
        return None

    @api.model
    def _http_get_json(self, url):
        """Plain urllib GET → JSON. Same pattern as the
        Etherscan/Tronscan syncers elsewhere in the module.
        """
        req = urllib.request.Request(
            url,
            headers={'User-Agent': 'odoo-jito-sca/17.0'},
        )
        with urllib.request.urlopen(req, timeout=self.HTTP_TIMEOUT) as resp:
            return json.loads(resp.read().decode('utf-8'))

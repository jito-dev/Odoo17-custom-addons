import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

ETHERSCAN_API_URL = 'https://api.etherscan.io/v2/api'
TRONSCAN_API_URL = 'https://apilist.tronscanapi.com'
ETH_LOG_INDEX = -1  # Sentinel: native ETH txs have no log index
TRC20_DEFAULT_LIMIT = 50
# Tronscan marks native TRX rows on /api/transfer with tokenName="_".
# Used as a client-side filter inside _sync_native_trx.
TRX_NATIVE_SENTINEL = '_'
TRX_DECIMALS = 6  # 1 TRX = 10^6 SUN
# Pagination safety cap for TRC-20 / TRX history fetches: 20 pages of
# 50 = 1000 transfers per sync per token. Prevents runaway loops on
# pathological accounts and bounds API consumption. Re-running sync
# after the cap is hit will pick up older transfers if the wallet had
# more than 1000 to begin with — at that volume the user should be
# pulling history less frequently anyway.
TRC20_MAX_PAGES = 20

# Tronscan rate limit (per their docs): 5 calls / second per API key.
# Throttle to 4 req/s (250 ms minimum interval) to stay safely under
# the cap even with mild clock skew / variable network latency. The
# state below is **process-local** — multi-worker setups would each
# throttle independently (worst case: workers × 4 r/s); upgrade to a
# shared limiter (redis / db row lock) if that becomes a problem.
TRONSCAN_MIN_INTERVAL = 0.25   # seconds
_TRONSCAN_LAST_CALL = [0.0]    # mutable container for process-wide state


class ScaWatchedAddress(models.Model):
    _name = 'sca.watched_address'
    _description = 'Watched Crypto Address'
    _order = 'name'

    name = fields.Char(string='Label', required=True)
    address = fields.Char(
        string='Wallet Address', required=True,
        help='ERC-20: 0x-prefixed hex (e.g. 0xAb…); TRC-20: T-prefixed '
             'base58 (e.g. TR7N…).',
    )
    network = fields.Selection(
        [('erc20', 'ERC-20 (Ethereum)'),
         ('trc20', 'TRC-20 (TRON)')],
        string='Network',
        required=True,
        default='erc20',
    )
    sync_eth_transfers = fields.Boolean(
        string='Sync Native ETH Transfers',
        default=False,
        help='Also download native ETH transfers (not just ERC-20 token transfers).',
    )
    eth_balance = fields.Float(string='ETH Balance', digits=(30, 8), readonly=True)
    sync_trx_transfers = fields.Boolean(
        string='Sync Native TRX Transfers',
        default=False,
        help='Also download native TRX transfers (not just TRC-20 token transfers). '
             'Mirrors the Sync Native ETH Transfers flag for ERC-20.',
    )
    trx_balance = fields.Float(string='TRX Balance', digits=(30, 8), readonly=True)
    active = fields.Boolean(default=True)
    last_sync_date = fields.Datetime(string='Last Sync', readonly=True)

    token_ids = fields.One2many('sca.token', 'watched_address_id', string='Watched Tokens')
    transaction_ids = fields.One2many('sca.transaction', 'watched_address_id', string='Transactions')
    transaction_count = fields.Integer(string='Transactions', compute='_compute_transaction_count', store=False)
    token_count = fields.Integer(string='Tokens', compute='_compute_token_count', store=False)

    _sql_constraints = [
        ('unique_address', 'UNIQUE(address)', 'This wallet address is already being watched.'),
    ]

    @api.depends('transaction_ids')
    def _compute_transaction_count(self):
        for rec in self:
            rec.transaction_count = len(rec.transaction_ids)

    @api.depends('token_ids')
    def _compute_token_count(self):
        for rec in self:
            rec.token_count = len(rec.token_ids)

    # ------------------------------------------------------------------
    # Public actions
    # ------------------------------------------------------------------

    def action_sync(self):
        self.ensure_one()

        if not self.token_ids \
                and not self.sync_eth_transfers \
                and not self.sync_trx_transfers:
            raise UserError(_(
                'Nothing to sync. Add at least one token or enable '
                '"Sync Native ETH Transfers" / "Sync Native TRX Transfers".'
            ))

        seen_hashes = set()
        total_new = 0

        if self.network == 'trc20':
            api_key = self._get_tronscan_api_key()  # may be empty
            for token in self.token_ids:
                total_new += self._sync_trc20_token(token, api_key, seen_hashes)
            if self.sync_trx_transfers:
                total_new += self._sync_native_trx(api_key, seen_hashes)
            # Refresh TRC-20 + TRX balances in the same pass.
            self._refresh_trc20_balances(api_key)
        else:
            api_key = self._get_api_key()
            for token in self.token_ids:
                total_new += self._sync_token(token, api_key, seen_hashes)
            if self.sync_eth_transfers:
                total_new += self._sync_eth(api_key, seen_hashes)
            self._refresh_balances(api_key)

        self.write({'last_sync_date': fields.Datetime.now()})

        if total_new == 0 and self.network == 'trc20':
            message = _(
                'Sync completed for %s but 0 new transactions were '
                'returned by Tronscan. Common causes: (1) the wallet '
                'has no recent transfers for the configured token(s); '
                '(2) the contract address is incorrect — TRC-20 '
                'contracts are case-sensitive base58 (e.g. USDT = '
                'TXLAQ63Xg1NAzckPwKHvzw7CSEmLMEqcdj); (3) the public '
                'tier rate-limited your IP — set a Tronscan API key in '
                'Settings. Run Debug Sync to see the raw API response.',
                self.name,
            )
            ntype = 'warning'
        else:
            message = _(
                '%d new transaction(s) imported for %s.',
                total_new, self.name,
            )
            ntype = 'success'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Sync Complete'),
                'message': message,
                'type': ntype,
                'sticky': ntype == 'warning',
            },
        }

    def action_sync_trc20_debug(self):
        """Diagnostic TRC-20 sync (17.0.5.0.0 — Tronscan).

        Probes both endpoints used by the sync flow:
          1. ``/api/transfer/trc20?address=…&trc20Id=…&limit=5&start=0``
          2. ``/api/account?address=…``

        Dumps each request URL, HTTP status, response top-level keys,
        item-array length, and the first item's keys + JSON dump
        (truncated) into a sticky notification. Pure read-only probe —
        writes nothing to ``sca.transaction``.
        """
        self.ensure_one()
        if self.network != 'trc20':
            raise UserError(_(
                'Debug Sync is only meaningful for TRC-20 addresses.'
            ))
        api_key = self._get_tronscan_api_key()
        buf = []
        if api_key:
            masked = '%s…%s' % (api_key[:4], api_key[-4:]) if len(api_key) > 8 else '(short)'
            buf.append('API key   : %s (%d chars)' % (masked, len(api_key)))
        else:
            buf.append('API key   : (none — using anonymous tier)')
        buf.append('Address   : %s' % self.address)
        buf.append('Provider  : Tronscan (apilist.tronscanapi.com)')
        buf.append('Tokens    : %d watched' % len(self.token_ids))
        if not self.token_ids:
            buf.append('!! No tokens configured. Add at least one in Watched Tokens.')

        # Probe 1 — per-token transfers (used by _sync_trc20_token).
        for token in self.token_ids:
            buf.append('')
            buf.append('=== TRANSFERS PROBE — %s ===' % (token.name or '?'))
            params = {
                'address': self.address,
                'trc20Id': token.contract_address,
                'limit': 5,
                'start': 0,
            }
            full = '%s/api/transfer/trc20?%s' % (
                TRONSCAN_API_URL, urllib.parse.urlencode(params),
            )
            buf.append('GET   : %s' % full)
            status, body = self._tronscan_get_raw(
                '/api/transfer/trc20', params, api_key,
            )
            buf.append('HTTP  : %s' % status)
            try:
                data = json.loads(body)
                keys = sorted(data.keys()) if isinstance(data, dict) else []
                buf.append('keys  : %s' % keys)
                items = data.get('token_transfers') or data.get('data') or []
                buf.append('items : %d' % (len(items) if isinstance(items, list) else -1))
                if isinstance(items, list) and items:
                    first = items[0]
                    buf.append('row[0]: keys=%s' % sorted(first.keys()))
                    buf.append('row[0]: %s' % json.dumps(first)[:700])
            except Exception as exc:
                buf.append('parse : %s' % str(exc)[:200])
                buf.append('body  : %s' % (body or '')[:400])

        # Probe 2 — wallet account / TRC-20 balances.
        buf.append('')
        buf.append('=== BALANCES PROBE ===')
        params = {'address': self.address}
        full = '%s/api/account?%s' % (
            TRONSCAN_API_URL, urllib.parse.urlencode(params),
        )
        buf.append('GET   : %s' % full)
        status, body = self._tronscan_get_raw('/api/account', params, api_key)
        buf.append('HTTP  : %s' % status)
        try:
            data = json.loads(body)
            keys = sorted(data.keys()) if isinstance(data, dict) else []
            buf.append('keys  : %s' % keys)
            entries = data.get('trc20token_balances') or []
            buf.append('trc20 : %d entries' % (len(entries) if isinstance(entries, list) else -1))
            if isinstance(entries, list) and entries:
                first = entries[0]
                buf.append('row[0]: keys=%s' % sorted(first.keys()))
                buf.append('row[0]: %s' % json.dumps(first)[:700])
        except Exception as exc:
            buf.append('parse : %s' % str(exc)[:200])
            buf.append('body  : %s' % (body or '')[:400])

        message = '\n'.join(buf)
        _logger.info('TRC-20 debug sync (Tronscan):\n%s', message)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('TRC-20 Debug Sync (Tronscan)'),
                'message': message,
                'type': 'info',
                'sticky': True,
            },
        }

    def action_remove_duplicates(self):
        self.ensure_one()
        self.env.cr.execute("""
            SELECT tx_hash
            FROM sca_transaction
            WHERE watched_address_id = %s
            GROUP BY tx_hash
            HAVING COUNT(*) > 1
        """, (self.id,))
        duplicate_hashes = [r[0] for r in self.env.cr.fetchall()]

        removed = 0
        Transaction = self.env['sca.transaction'].sudo()
        for tx_hash in duplicate_hashes:
            records = Transaction.search([
                ('watched_address_id', '=', self.id),
                ('tx_hash', '=', tx_hash),
            ])
            # Keep the record with token_id set (meaningful token transfer), else keep the first
            to_keep = records.filtered(lambda r: r.token_id)[:1] or records[:1]
            to_delete = records - to_keep
            removed += len(to_delete)
            to_delete.unlink()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Duplicates Removed'),
                'message': _('%d duplicate transaction(s) removed for %s.', removed, self.name),
                'type': 'success' if removed else 'info',
                'sticky': False,
            },
        }

    def action_refresh_balances(self):
        self.ensure_one()
        if self.network == 'trc20':
            api_key = self._get_tronscan_api_key()
            self._refresh_trc20_balances(api_key)
        else:
            api_key = self._get_api_key()
            self._refresh_balances(api_key)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Balances Updated'),
                'message': _('Balances refreshed for %s.', self.name),
                'type': 'success',
                'sticky': False,
            },
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_api_key(self):
        settings = self.env['sca.settings']._get_singleton()
        api_key = settings.sudo().etherscan_api_key
        if not api_key:
            raise UserError(_('Please configure your Etherscan API key in Settings before syncing.'))
        return api_key

    def _get_tronscan_api_key(self):
        """Return the Tronscan API key, or '' if the user wants the
        anonymous public tier (17.0.5.0.0).

        Tronscan's public endpoints work without a key for low volume.
        If a key is configured, we send it as ``TRON-PRO-API-KEY``
        which Tronscan also accepts (same header convention as
        TronGrid).
        """
        settings = self.env['sca.settings']._get_singleton()
        return (settings.sudo().tronscan_api_key or '').strip()

    def _etherscan_get(self, params, api_key):
        """Execute a GET request against the Etherscan V2 API. Returns parsed JSON."""
        params.update({'apikey': api_key, 'chainid': 1})
        url = '%s?%s' % (ETHERSCAN_API_URL, urllib.parse.urlencode(params))
        req = urllib.request.Request(
            url,
            headers={'User-Agent': 'Mozilla/5.0 (compatible; OdooSimpleCryptoAccounting/1.0)'},
            method='GET',
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            body = exc.read().decode()
            _logger.error('Etherscan HTTP %s: %s', exc.code, body[:300])
            raise UserError(_('Etherscan API error %s: %s', exc.code, body[:200]))
        except Exception as exc:
            _logger.error('Etherscan connection error: %s', exc)
            raise UserError(_('Failed to connect to Etherscan: %s', str(exc)))

    @staticmethod
    def _tronscan_throttle():
        """Sleep just long enough to keep the process under Tronscan's
        5 req/s rate limit (17.0.8.2.0). Every call site funnels
        through ``_tronscan_get`` / ``_tronscan_get_raw`` which call
        this before firing the request, so per-process throughput is
        bounded at 1 / ``TRONSCAN_MIN_INTERVAL`` ≈ 4 req/s.
        """
        now = time.monotonic()
        wait = TRONSCAN_MIN_INTERVAL - (now - _TRONSCAN_LAST_CALL[0])
        if wait > 0:
            time.sleep(wait)
        _TRONSCAN_LAST_CALL[0] = time.monotonic()

    def _tronscan_get(self, path, params, api_key=''):
        """Execute a GET against Tronscan's public API (17.0.5.0.0;
        rate-limited in 17.0.8.2.0).

        ``path`` is the URL path without the host, e.g.
        ``/api/transfer/trc20``. ``api_key`` is optional; when
        non-empty we send it as ``TRON-PRO-API-KEY``. Returns parsed
        JSON. Raises ``UserError`` with the response body on HTTP errors.
        """
        self._tronscan_throttle()
        url = '%s%s' % (TRONSCAN_API_URL, path)
        if params:
            url = '%s?%s' % (url, urllib.parse.urlencode(params))
        headers = {
            'User-Agent': 'Mozilla/5.0 (compatible; OdooSimpleCryptoAccounting/1.0)',
            'Accept': 'application/json',
        }
        if api_key:
            headers['TRON-PRO-API-KEY'] = api_key
        req = urllib.request.Request(url, headers=headers, method='GET')
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            body = exc.read().decode()
            _logger.error('Tronscan HTTP %s: %s', exc.code, body[:400])
            if exc.code == 429:
                raise UserError(_(
                    "Tronscan rate-limited the request (HTTP 429). Free "
                    "API keys are capped at 5 calls/second; the local "
                    "throttle keeps each Odoo process under 4/s but "
                    "multi-worker Odoo setups can collectively exceed "
                    "that. Wait a minute and retry, or upgrade your "
                    "Tronscan plan for a higher per-key limit. Raw "
                    "response: %s", body[:200],
                ))
            raise UserError(_(
                'Tronscan API error %s: %s',
                exc.code, body[:300],
            ))
        except Exception as exc:
            _logger.error('Tronscan connection error: %s', exc)
            raise UserError(_(
                'Failed to connect to Tronscan: %s', str(exc),
            ))

    def _tronscan_get_raw(self, path, params, api_key=''):
        """Like ``_tronscan_get`` but returns ``(http_status, body)``
        on every outcome — no exceptions, no UserError. Used by Debug
        Sync to show the raw response without aborting. Rate-limited
        (17.0.8.2.0).
        """
        self._tronscan_throttle()
        url = '%s%s' % (TRONSCAN_API_URL, path)
        if params:
            url = '%s?%s' % (url, urllib.parse.urlencode(params))
        headers = {
            'User-Agent': 'Mozilla/5.0 (compatible; OdooSimpleCryptoAccounting/1.0)',
            'Accept': 'application/json',
        }
        if api_key:
            headers['TRON-PRO-API-KEY'] = api_key
        req = urllib.request.Request(url, headers=headers, method='GET')
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status, resp.read().decode()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode()
        except Exception as exc:
            return -1, '(connection error) %s' % str(exc)

    @staticmethod
    def _first_nonempty(row, *keys):
        """Return the first non-empty stringy value from ``row`` for
        any of ``keys``. Useful when an API returns the same logical
        field under different names across endpoints / versions.
        """
        for key in keys:
            value = row.get(key)
            if value not in (None, '', False):
                return value
        return ''

    def _parse_timestamp(self, ts):
        try:
            return datetime.fromtimestamp(int(ts), tz=timezone.utc).replace(tzinfo=None)
        except (ValueError, TypeError):
            return False

    def _tx_exists(self, tx_hash, from_addr='', to_addr='', raw_value='', seen_events=None):
        """Composite-key dedup (17.0.8.3.0).

        A single TRON transaction can emit multiple Transfer events
        (DEX swaps, batch payouts) — they share ``tx_hash`` but differ
        in at least one of from/to/amount. So dedup is the tuple
        ``(tx_hash, from, to, raw_value)`` instead of just ``tx_hash``.

        ``seen_events`` is the in-request memo set — a set of those
        tuples, populated by the caller as each row is processed.
        """
        key = (
            tx_hash or '',
            from_addr or '',
            to_addr or '',
            str(raw_value or ''),
        )
        if seen_events is not None and key in seen_events:
            return True
        return bool(self.env['sca.transaction'].sudo().search([
            ('tx_hash', '=', tx_hash),
            ('from_address', '=', from_addr or False),
            ('to_address', '=', to_addr or False),
            ('raw_value', '=', str(raw_value or '0')),
        ], limit=1))

    def _refresh_balances(self, api_key):
        """Fetch and store current ETH + token balances from Etherscan."""
        # ETH balance
        if self.sync_eth_transfers:
            data = self._etherscan_get({
                'module': 'account',
                'action': 'balance',
                'address': self.address,
                'tag': 'latest',
            }, api_key)
            if data.get('status') == '1':
                try:
                    self.eth_balance = int(data['result']) / (10 ** 18)
                except (ValueError, TypeError):
                    pass

        # Token balances
        for token in self.token_ids:
            data = self._etherscan_get({
                'module': 'account',
                'action': 'tokenbalance',
                'address': self.address,
                'contractaddress': token.contract_address,
                'tag': 'latest',
            }, api_key)
            if data.get('status') == '1':
                try:
                    token.balance = int(data['result']) / (10 ** token.decimals)
                except (ValueError, TypeError):
                    pass

    def _sync_token(self, token, api_key, seen_hashes=None):
        """Fetch ERC-20 token transfers from Etherscan. Returns count of new records."""
        data = self._etherscan_get({
            'module': 'account',
            'action': 'tokentx',
            'address': self.address,
            'contractaddress': token.contract_address,
            'startblock': 0,
            'endblock': 99999999,
            'sort': 'desc',
        }, api_key)

        message = data.get('message', '')
        if data.get('status') == '0' and message not in ('No transactions found', 'No records found'):
            raise UserError(_('Etherscan returned an error: %s', str(data.get('result', ''))[:200]))

        rows = data.get('result') or []
        if not isinstance(rows, list):
            return 0

        Transaction = self.env['sca.transaction'].sudo()
        new_count = 0
        for row in rows:
            tx_hash = row.get('hash', '')
            if not tx_hash or row.get('value', '0') == '0':
                continue
            from_addr = row.get('from', '')
            to_addr = row.get('to', '')
            raw_value = row.get('value', '0')
            if self._tx_exists(tx_hash, from_addr, to_addr, raw_value, seen_hashes):
                continue

            Transaction.create({
                'watched_address_id': self.id,
                'token_id': token.id,
                'tx_hash': tx_hash,
                'log_index': int(row.get('logIndex', 0) or 0),
                'block_number': int(row.get('blockNumber', 0) or 0),
                'tx_date': self._parse_timestamp(row.get('timeStamp', '0')),
                'from_address': from_addr,
                'to_address': to_addr,
                'raw_value': raw_value,
                'token_symbol': row.get('tokenSymbol', token.name),
                'token_contract': row.get('contractAddress', token.contract_address),
                'gas_used': int(row.get('gasUsed', 0) or 0),
            })
            if seen_hashes is not None:
                seen_hashes.add((tx_hash, from_addr, to_addr, str(raw_value)))
            new_count += 1

        return new_count

    def _sync_eth(self, api_key, seen_hashes=None):
        """Fetch native ETH transactions from Etherscan. Returns count of new records."""
        data = self._etherscan_get({
            'module': 'account',
            'action': 'txlist',
            'address': self.address,
            'startblock': 0,
            'endblock': 99999999,
            'sort': 'desc',
        }, api_key)

        message = data.get('message', '')
        if data.get('status') == '0' and message not in ('No transactions found', 'No records found'):
            raise UserError(_('Etherscan returned an error: %s', str(data.get('result', ''))[:200]))

        rows = data.get('result') or []
        if not isinstance(rows, list):
            return 0

        Transaction = self.env['sca.transaction'].sudo()
        new_count = 0
        for row in rows:
            tx_hash = row.get('hash', '')
            if not tx_hash or row.get('isError') == '1':
                continue
            # Skip contract calls with no ETH value (already captured by tokentx)
            if row.get('value', '0') == '0':
                continue
            from_addr = row.get('from', '')
            to_addr = row.get('to', '')
            raw_value = row.get('value', '0')
            if self._tx_exists(tx_hash, from_addr, to_addr, raw_value, seen_hashes):
                continue

            Transaction.create({
                'watched_address_id': self.id,
                'token_id': False,
                'tx_hash': tx_hash,
                'log_index': ETH_LOG_INDEX,
                'block_number': int(row.get('blockNumber', 0) or 0),
                'tx_date': self._parse_timestamp(row.get('timeStamp', '0')),
                'from_address': from_addr,
                'to_address': to_addr,
                'raw_value': raw_value,
                'token_symbol': 'ETH',
                'token_contract': '',
                'gas_used': int(row.get('gasUsed', 0) or 0),
            })
            if seen_hashes is not None:
                seen_hashes.add((tx_hash, from_addr, to_addr, str(raw_value)))
            new_count += 1

        return new_count

    # ------------------------------------------------------------------
    # TRC-20 sync (17.0.3.0.0)
    # ------------------------------------------------------------------

    def _sync_trc20_token(self, token, api_key, seen_hashes=None):
        """Fetch TRC-20 token transfers via Tronscan (17.0.5.0.0).

        Endpoint:
            GET /api/transfer/trc20
                ?address={wallet}
                &trc20Id={contract_address}
                &limit=50&start=0

        Tronscan response (canonical shape):
            {
              "token_transfers": [
                {
                  "transaction_id": "<hex tx hash, no 0x>",
                  "block_ts": <ms since epoch>,
                  "from_address": "T...",
                  "to_address":   "T...",
                  "contract_address": "T...",
                  "quant": "<raw integer string in base units>",
                  "tokenInfo": {
                    "tokenAbbr": "USDT",
                    "tokenName": "Tether USD",
                    "tokenDecimal": 6,
                    "tokenType": "trc20",
                    ...
                  },
                  ...
                },
                ...
              ],
              "total": N,
              "rangeTotal": N
            }

        17.0.8.1.0 — paginates via `start` (page offset) until either
        the page comes back empty / short, or zero new rows were
        inserted on a page (steady-state delta sync — we've reached
        already-imported territory). Capped at ``TRC20_MAX_PAGES`` to
        prevent runaway on huge histories; re-run sync to fetch older
        transfers beyond the cap.

        17.0.8.4.0 — explicitly iterates **both** directions: the
        endpoint's default (no `direction` param) returns only one side
        (typically *sent*), so inbound transfers were silently missing
        for outbound-only wallets. Tronscan's convention:
        ``direction=1`` = sent, ``direction=2`` = received. We pull
        each separately; the composite dedup catches any overlap.
        """
        Transaction = self.env['sca.transaction'].sudo()
        new_count = 0
        # ('1', 'sent') first, then ('2', 'received') — outbound usually
        # has more recent activity than inbound on treasuries, so most
        # syncs early-exit on the smaller half second.
        for direction, dir_label in (('1', 'sent'), ('2', 'received')):
            for page in range(TRC20_MAX_PAGES):
                params = {
                    'address': self.address,
                    'trc20Id': token.contract_address,
                    'limit': TRC20_DEFAULT_LIMIT,
                    'start': page * TRC20_DEFAULT_LIMIT,
                    'direction': direction,
                }
                data = self._tronscan_get('/api/transfer/trc20', params, api_key)
                # Tronscan returns the array under different keys depending
                # on the endpoint version: `data` (current), `token_transfers`
                # (older), `transfers` (some hosts). Accept all variants.
                items = (
                    data.get('data')
                    or data.get('token_transfers')
                    or data.get('transfers')
                    or []
                )
                if isinstance(items, dict):
                    items = items.get('list') or items.get('items') or []
                if not isinstance(items, list):
                    items = []
                if not items:
                    break

                page_new = 0
                for row in items:
                    tx_hash = (row.get('transaction_id') or row.get('hash') or '').strip()
                    if not tx_hash:
                        continue
                    raw_value = str(row.get('quant') or row.get('amount') or '0').strip()
                    if raw_value in ('', '0'):
                        continue
                    from_addr = self._first_nonempty(
                        row, 'from_address', 'transferFromAddress', 'fromAddress', 'from',
                    )
                    to_addr = self._first_nonempty(
                        row, 'to_address', 'transferToAddress', 'toAddress', 'to',
                    )
                    if not (from_addr and to_addr):
                        _logger.warning(
                            'TRC-20 row missing from/to — addr=%s tx=%s row keys=%s',
                            self.address, tx_hash[:12], sorted(row.keys()),
                        )
                    if self._tx_exists(tx_hash, from_addr, to_addr, raw_value, seen_hashes):
                        continue
                    ts_ms = row.get('block_ts') or row.get('block_timestamp') or 0
                    try:
                        ts_int = int(ts_ms)
                        tx_date = datetime.fromtimestamp(ts_int / 1000.0, tz=timezone.utc).replace(tzinfo=None) \
                            if ts_int else False
                    except (TypeError, ValueError):
                        tx_date = False
                    token_info = row.get('tokenInfo') or {}
                    Transaction.create({
                        'watched_address_id': self.id,
                        'token_id': token.id,
                        'tx_hash': tx_hash,
                        'log_index': 0,
                        'block_number': int(row.get('block') or 0) or 0,
                        'tx_date': tx_date or fields.Datetime.now(),
                        'from_address': from_addr,
                        'to_address': to_addr,
                        'raw_value': raw_value,
                        'token_symbol': token_info.get('tokenAbbr') or token.name,
                        'token_contract': row.get('contract_address') or token.contract_address,
                        'gas_used': 0,
                    })
                    if seen_hashes is not None:
                        seen_hashes.add((tx_hash, from_addr or '', to_addr or '', str(raw_value)))
                    page_new += 1
                new_count += page_new
                _logger.info(
                    'TRC-20 sync via Tronscan: addr=%s token=%s dir=%s page=%d '
                    'fetched=%d inserted=%d running_total=%d',
                    self.address, token.name, dir_label, page, len(items),
                    page_new, new_count,
                )
                # Stop early when:
                #   * the page returned fewer rows than the limit (end of
                #     available data); or
                #   * the page introduced zero new rows (delta sync caught
                #     up to previously-imported transactions).
                # Breaks the page loop only — the outer direction loop
                # then proceeds to the other direction.
                if len(items) < TRC20_DEFAULT_LIMIT or page_new == 0:
                    break

        return new_count

    def _sync_native_trx(self, api_key, seen_hashes=None):
        """Fetch native TRX transfers via Tronscan (17.0.5.2.0;
        paginated in 17.0.8.1.0).

        Endpoint:
            GET /api/transfer?address={addr}&limit=50&start=N

        Mirrors ``_sync_eth`` for ERC-20: wallet-level, no parent
        ``sca.token`` row needed. The unified ``/api/transfer`` endpoint
        returns a mixed TRX + token stream, so we filter client-side to
        rows with ``tokenName == '_'`` (Tronscan's native-TRX marker).

        17.0.8.4.0 — iterates ``direction=1`` (sent) and ``direction=2``
        (received) explicitly, same as ``_sync_trc20_token``. The
        endpoint's default returns one side only, which silently hid
        inbound TRX. Composite dedup catches any overlap.
        """
        Transaction = self.env['sca.transaction'].sudo()
        new_count = 0
        for direction, dir_label in (('1', 'sent'), ('2', 'received')):
            for page in range(TRC20_MAX_PAGES):
                params = {
                    'address': self.address,
                    'limit': TRC20_DEFAULT_LIMIT,
                    'start': page * TRC20_DEFAULT_LIMIT,
                    'sort': '-timestamp',
                    'direction': direction,
                }
                data = self._tronscan_get('/api/transfer', params, api_key)
                items = (
                    data.get('data')
                    or data.get('transfers')
                    or []
                )
                if isinstance(items, dict):
                    items = items.get('list') or items.get('items') or []
                if not isinstance(items, list):
                    items = []
                if not items:
                    break

                page_new = 0
                for row in items:
                    # Filter to native TRX only — Tronscan uses tokenName="_"
                    # for the chain's native asset; TRC-20 transfers carry
                    # the token's symbol there. tokenInfo.tokenId="_" is a
                    # defensive alternate check.
                    token_name = (row.get('tokenName') or '').strip()
                    tinfo = row.get('tokenInfo') or {}
                    tinfo_id = (tinfo.get('tokenId') or '').strip() if isinstance(tinfo, dict) else ''
                    if token_name and token_name != TRX_NATIVE_SENTINEL \
                            and tinfo_id and tinfo_id != TRX_NATIVE_SENTINEL:
                        continue
                    tx_hash = (row.get('transactionHash') or row.get('hash') or '').strip()
                    if not tx_hash:
                        continue
                    raw_value = str(row.get('amount') or '0').strip()
                    if raw_value in ('', '0'):
                        continue
                    from_addr = self._first_nonempty(
                        row, 'transferFromAddress', 'from_address', 'fromAddress', 'from',
                    )
                    to_addr = self._first_nonempty(
                        row, 'transferToAddress', 'to_address', 'toAddress', 'to',
                    )
                    if not (from_addr and to_addr):
                        _logger.warning(
                            'TRX row missing from/to — addr=%s tx=%s row keys=%s',
                            self.address, tx_hash[:12], sorted(row.keys()),
                        )
                    if self._tx_exists(tx_hash, from_addr, to_addr, raw_value, seen_hashes):
                        continue
                    ts_ms = row.get('timestamp') or row.get('block_ts') or 0
                    try:
                        ts_int = int(ts_ms)
                        tx_date = datetime.fromtimestamp(ts_int / 1000.0, tz=timezone.utc).replace(tzinfo=None) \
                            if ts_int else False
                    except (TypeError, ValueError):
                        tx_date = False
                    Transaction.create({
                        'watched_address_id': self.id,
                        'token_id': False,
                        'tx_hash': tx_hash,
                        'log_index': ETH_LOG_INDEX,
                        'block_number': int(row.get('block') or 0) or 0,
                        'tx_date': tx_date or fields.Datetime.now(),
                        'from_address': from_addr,
                        'to_address': to_addr,
                        'raw_value': raw_value,
                        'token_symbol': 'TRX',
                        'token_contract': '',
                        'gas_used': 0,
                    })
                    if seen_hashes is not None:
                        seen_hashes.add((tx_hash, from_addr or '', to_addr or '', str(raw_value)))
                    page_new += 1
                new_count += page_new
                _logger.info(
                    'TRX native sync via Tronscan: addr=%s dir=%s page=%d '
                    'fetched=%d inserted=%d running_total=%d',
                    self.address, dir_label, page, len(items),
                    page_new, new_count,
                )
                if len(items) < TRC20_DEFAULT_LIMIT or page_new == 0:
                    break

        return new_count

    def _refresh_trc20_balances(self, api_key):
        """Update ``balance`` on each watched TRC-20 token via Tronscan
        (17.0.5.0.0).

        Endpoint:
            GET /api/account?address={wallet}

        Tronscan response (relevant subset):
            {
              "address": "T...",
              "balance": <SUN integer>,         # native TRX
              "trc20token_balances": [
                {
                  "tokenId":     "T...contract...",
                  "balance":     "<raw integer string>",
                  "tokenAbbr":   "USDT",
                  "tokenName":   "Tether USD",
                  "tokenDecimal": 6,
                  ...
                },
                ...
              ],
              ...
            }

        Match each watched token by `contract_address` and divide the
        raw balance by `10^decimals`.
        """
        data = self._tronscan_get(
            '/api/account', {'address': self.address}, api_key,
        )
        # Native TRX balance lives at the response root as a SUN
        # integer. Always written into ``trx_balance`` on the wallet —
        # the view hides the field unless sync_trx_transfers is on, but
        # storing the value unconditionally keeps it accurate if the
        # user toggles the flag later.
        trx_balance_sun = data.get('balance') or 0
        try:
            trx_balance_sun = int(trx_balance_sun)
        except (TypeError, ValueError):
            trx_balance_sun = 0
        self.sudo().trx_balance = trx_balance_sun / (10 ** TRX_DECIMALS)

        entries = data.get('trc20token_balances') or []
        # Map: contract_address (lower) → (raw_balance_str, tokenDecimal).
        balance_map = {}
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            contract = (entry.get('tokenId') or '').lower()
            if not contract:
                continue
            balance_map[contract] = (
                str(entry.get('balance') or '0'),
                int(entry.get('tokenDecimal') or 0),
            )
        if not balance_map and not trx_balance_sun:
            _logger.warning(
                'Tronscan returned no TRC-20 or TRX balances for %s — '
                'wallet may be unactivated or hold zero balances.',
                self.address,
            )
        for token in self.token_ids:
            key = (token.contract_address or '').lower()
            raw, decimals = balance_map.get(key, ('0', token.decimals or 0))
            try:
                raw_int = int(raw)
            except (TypeError, ValueError):
                raw_int = 0
            decimals = decimals or token.decimals or 0
            token.sudo().balance = raw_int / (10 ** decimals) if decimals else raw_int

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

ETHERSCAN_API_URL = 'https://api.etherscan.io/v2/api'
ETH_LOG_INDEX = -1  # Sentinel: native ETH txs have no log index


class ScaWatchedAddress(models.Model):
    _name = 'sca.watched_address'
    _description = 'Watched Crypto Address'
    _order = 'name'

    name = fields.Char(string='Label', required=True)
    address = fields.Char(string='Wallet Address', required=True, help='Ethereum address (0x...)')
    network = fields.Selection(
        [('erc20', 'ERC-20')],
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

        api_key = self._get_api_key()

        if not self.token_ids and not self.sync_eth_transfers:
            raise UserError(_('Nothing to sync. Add at least one token or enable "Sync Native ETH Transfers".'))

        seen_hashes = set()
        total_new = 0
        for token in self.token_ids:
            total_new += self._sync_token(token, api_key, seen_hashes)

        if self.sync_eth_transfers:
            total_new += self._sync_eth(api_key, seen_hashes)

        self._refresh_balances(api_key)
        self.write({'last_sync_date': fields.Datetime.now()})

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Sync Complete'),
                'message': _('%d new transaction(s) imported for %s.', total_new, self.name),
                'type': 'success',
                'sticky': False,
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

    def _parse_timestamp(self, ts):
        try:
            return datetime.fromtimestamp(int(ts), tz=timezone.utc).replace(tzinfo=None)
        except (ValueError, TypeError):
            return False

    def _tx_exists(self, tx_hash, seen_hashes=None):
        if seen_hashes is not None and tx_hash in seen_hashes:
            return True
        return bool(self.env['sca.transaction'].sudo().search(
            [('tx_hash', '=', tx_hash)], limit=1
        ))

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
            if self._tx_exists(tx_hash, seen_hashes):
                continue

            Transaction.create({
                'watched_address_id': self.id,
                'token_id': token.id,
                'tx_hash': tx_hash,
                'log_index': int(row.get('logIndex', 0) or 0),
                'block_number': int(row.get('blockNumber', 0) or 0),
                'tx_date': self._parse_timestamp(row.get('timeStamp', '0')),
                'from_address': row.get('from', ''),
                'to_address': row.get('to', ''),
                'raw_value': row.get('value', '0'),
                'token_symbol': row.get('tokenSymbol', token.name),
                'token_contract': row.get('contractAddress', token.contract_address),
                'gas_used': int(row.get('gasUsed', 0) or 0),
            })
            if seen_hashes is not None:
                seen_hashes.add(tx_hash)
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
            if self._tx_exists(tx_hash, seen_hashes):
                continue

            Transaction.create({
                'watched_address_id': self.id,
                'token_id': False,
                'tx_hash': tx_hash,
                'log_index': ETH_LOG_INDEX,
                'block_number': int(row.get('blockNumber', 0) or 0),
                'tx_date': self._parse_timestamp(row.get('timeStamp', '0')),
                'from_address': row.get('from', ''),
                'to_address': row.get('to', ''),
                'raw_value': row.get('value', '0'),
                'token_symbol': 'ETH',
                'token_contract': '',
                'gas_used': int(row.get('gasUsed', 0) or 0),
            })
            if seen_hashes is not None:
                seen_hashes.add(tx_hash)
            new_count += 1

        return new_count

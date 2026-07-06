import datetime
import json
import logging
import urllib.error
import urllib.request
import uuid

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class RevolutAccountJournalMap(models.Model):
    _name = 'revolut.account.journal.map'
    _description = 'Revolut Account ↔ Odoo Journal Mapping'
    _rec_name = 'revolut_account_name'
    _order = 'revolut_account_name'

    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        default=lambda self: self.env.company, index=True,
    )
    config_id = fields.Many2one(
        'legacy.accounting.config', string='Configuration',
        ondelete='cascade', index=True,
    )
    is_manual = fields.Boolean(
        string='Manual Account', default=False,
        help='True for manually created accounts (e.g. Flexible Cash Funds).',
    )
    source = fields.Selection(
        [('api', 'API'), ('manual', 'Manual / FCF')],
        string='Source', compute='_compute_source', store=True,
    )
    revolut_account_id = fields.Char(
        string='Revolut Account ID', required=True, index=True,
    )
    revolut_account_name = fields.Char(
        string='Revolut Account Name',
    )
    journal_id = fields.Many2one(
        'account.journal', string='Odoo Bank Journal',
        domain="[('type', '=', 'bank'), ('company_id', '=', company_id)]",
        help='Select the Odoo bank journal that corresponds to this Revolut account.',
    )
    currency_id = fields.Many2one(
        'res.currency', string='Currency',
    )

    # ── FCF (money-market-fund) accounting, per account ──────────────────────
    is_fcf = fields.Boolean(
        string='FCF Account',
        help='Mark this Revolut account as a Flexible Cash Fund (money-market fund). '
             'When set, configure below where its FCF transaction types post; the '
             'injector uses these accounts for this account’s FCF lines.')
    fcf_interest_income_account_id = fields.Many2one(
        'account.account', string='Interest Income (PAID)',
        domain="[('account_type', 'in', ('income', 'income_other')), ('deprecated', '=', False)]",
        help='Counterpart for "Interest PAID" lines (the real interest earned).')
    fcf_service_fee_account_id = fields.Many2one(
        'account.account', string='Service Fees',
        domain="[('account_type', '=', 'expense'), ('deprecated', '=', False)]",
        help='Counterpart for "Service Fee Charged" lines.')
    fcf_suspense_account_id = fields.Many2one(
        'account.account', string='Internal Suspense (Reinvested/Withdrawn)',
        domain="[('account_type', 'in', ('asset_current', 'asset_cash')), ('deprecated', '=', False)]",
        help='Counterpart for "Interest Reinvested" / "Interest WITHDRAWN" lines — '
             'Revolut-internal moves that do not change the real balance (parked, not P&L).')
    revolut_account_state = fields.Selection(
        [('active', 'Active'), ('inactive', 'Inactive')],
        string='Account State', readonly=True,
    )
    revolut_public = fields.Boolean(
        string='Public', readonly=True,
    )
    revolut_created_at = fields.Datetime(
        string='Created At (Revolut)', readonly=True,
    )
    revolut_updated_at = fields.Datetime(
        string='Updated At (Revolut)', readonly=True,
    )
    iban = fields.Char(string='IBAN', readonly=True)
    bic = fields.Char(string='BIC', readonly=True)
    sort_code = fields.Char(string='Sort Code', readonly=True)
    account_no = fields.Char(string='Account Number', readonly=True)
    routing_number = fields.Char(string='Routing Number', readonly=True)
    beneficiary = fields.Char(string='Beneficiary', readonly=True)
    bank_country = fields.Char(string='Bank Country', readonly=True)
    raw_json = fields.Text(string='Raw API Response', readonly=True)
    last_sync_balance = fields.Float(
        string='Last Revolut Balance', digits=(16, 4), readonly=True,
    )
    last_verified_at = fields.Datetime(
        string='Last Verified At', readonly=True,
    )
    odoo_balance = fields.Float(
        string='Odoo Journal Balance', digits=(16, 4),
        compute='_compute_odoo_balance',
    )
    fcf_transaction_count = fields.Integer(
        string='FCF Transactions',
        compute='_compute_fcf_transaction_count',
    )

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        defaults['is_manual'] = True
        defaults['revolut_account_id'] = f'manual_{uuid.uuid4().hex[:16]}'
        return defaults

    _sql_constraints = [
        (
            'revolut_account_company_uniq',
            'unique(revolut_account_id, company_id)',
            'A mapping for this Revolut account already exists for this company.',
        ),
    ]

    @api.depends('is_manual')
    def _compute_source(self):
        for rec in self:
            rec.source = 'manual' if rec.is_manual else 'api'

    @api.depends('journal_id')
    def _compute_odoo_balance(self):
        for rec in self:
            if not rec.journal_id:
                rec.odoo_balance = 0.0
                continue
            # Sum all posted statement line amounts for this journal
            self.env.cr.execute("""
                SELECT COALESCE(SUM(absl.amount), 0)
                FROM account_bank_statement_line absl
                JOIN account_move am ON am.id = absl.move_id
                WHERE am.journal_id = %s
                  AND am.state = 'posted'
            """, (rec.journal_id.id,))
            rec.odoo_balance = self.env.cr.fetchone()[0]

    FCF_TYPES = ['fcf_buy', 'fcf_sell', 'fcf_interest', 'fcf_fee']

    def _compute_fcf_transaction_count(self):
        RevTx = self.env['revolut.transaction']
        for rec in self:
            rec.fcf_transaction_count = RevTx.search_count([
                ('account_revolut_id', '=', rec.revolut_account_id),
                ('transaction_type', 'in', self.FCF_TYPES),
            ])

    def action_view_fcf_transactions(self):
        """Open transactions filtered to FCF types for this account."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'FCF Transactions — {self.revolut_account_name or self.revolut_account_id}',
            'res_model': 'revolut.transaction',
            'view_mode': 'tree,form',
            'domain': [
                ('account_revolut_id', '=', self.revolut_account_id),
                ('transaction_type', 'in', self.FCF_TYPES),
            ],
            'context': {'default_account_revolut_id': self.revolut_account_id},
        }

    def action_verify_balance(self):
        """Fetch current balance from Revolut API and compare with Odoo journal balance."""
        self.ensure_one()
        if not self.journal_id:
            raise UserError('Please link an Odoo bank journal first.')

        config = self.env['legacy.accounting.config'].sudo().search(
            [('company_id', '=', self.company_id.id)], limit=1
        )
        if not config or not config.access_token:
            raise UserError(
                'No access token found. '
                'Complete Step 4 in Revolut Business API Integration first.'
            )

        token = config.access_token.strip()

        # Fetch accounts from Revolut API
        url = f'https://b2b.revolut.com/api/1.0/accounts/{self.revolut_account_id}'
        req = urllib.request.Request(url)
        req.add_header('Accept', 'application/json')
        req.add_header('Authorization', f'Bearer {token}')
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                account_data = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 401:
                new_token = config._do_refresh_token()
                if new_token:
                    req = urllib.request.Request(url)
                    req.add_header('Accept', 'application/json')
                    req.add_header('Authorization', f'Bearer {new_token}')
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        account_data = json.loads(resp.read().decode())
                else:
                    raise UserError('Token expired and auto-refresh failed.')
            else:
                raise UserError(f'Revolut API error {e.code}: {e.read().decode()}')
        except Exception as e:
            raise UserError(f'Request failed: {e}')

        revolut_balance = account_data.get('balance', 0.0)
        self.write({
            'last_sync_balance': revolut_balance,
            'last_verified_at': fields.Datetime.now(),
        })

        # Recompute odoo_balance
        self._compute_odoo_balance()
        odoo_bal = self.odoo_balance
        diff = revolut_balance - odoo_bal

        if abs(diff) < 0.01:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Balance Verified',
                    'message': (
                        f'Revolut: {revolut_balance:.2f} | '
                        f'Odoo: {odoo_bal:.2f} — Balances match!'
                    ),
                    'type': 'success',
                    'sticky': False,
                },
            }
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Balance Mismatch',
                'message': (
                    f'Revolut: {revolut_balance:.2f} | '
                    f'Odoo: {odoo_bal:.2f} | '
                    f'Difference: {diff:+.2f}. '
                    f'Check date range or inject missing transactions.'
                ),
                'type': 'warning',
                'sticky': True,
            },
        }

    def action_sync_transactions(self):
        """Sync Revolut transactions for this specific account only."""
        self.ensure_one()

        config = self.env['legacy.accounting.config'].sudo().search(
            [('company_id', '=', self.company_id.id)], limit=1
        )
        if not config or not config.access_token:
            raise UserError(
                'No access token found. '
                'Complete Step 4 in Revolut Business API Integration first.'
            )

        token = config.access_token.strip()
        RevTx = self.env['revolut.transaction']
        account_id = self.revolut_account_id
        account_name = self.revolut_account_name or account_id

        created_count = 0
        updated_count = 0
        to_param = None

        while True:
            params = {'account': account_id, 'count': 1000}
            if to_param:
                params['to'] = to_param

            transactions = RevTx._revolut_get('/transactions', token, params=params)
            if not isinstance(transactions, list) or not transactions:
                break

            for tx_data in transactions:
                was_existing = RevTx._upsert_transaction(tx_data, account_id, account_name)
                if was_existing:
                    updated_count += 1
                else:
                    created_count += 1

            if len(transactions) < 1000:
                break

            oldest_dt_str = transactions[-1].get('created_at', '')
            if not oldest_dt_str:
                break
            try:
                dt = datetime.datetime.fromisoformat(
                    oldest_dt_str.replace('Z', '+00:00')
                )
                dt = dt - datetime.timedelta(milliseconds=1)
                to_param = dt.strftime('%Y-%m-%dT%H:%M:%S.') + \
                           f'{dt.microsecond // 1000:03d}Z'
            except Exception:
                break

        total = created_count + updated_count
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Sync Complete',
                'message': (
                    f'Account "{account_name}": synced {total} transactions — '
                    f'{created_count} new, {updated_count} updated.'
                ),
                'type': 'success',
                'sticky': True,
            },
        }

    def action_open_fcf_import(self):
        """Open the FCF CSV import wizard for this manual account."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Import FCF CSV',
            'res_model': 'fcf.csv.import.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_account_map_id': self.id,
            },
        }

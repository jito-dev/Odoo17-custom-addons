import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

UPWORK_AUTH_URL = 'https://www.upwork.com/ab/account-security/oauth2/authorize'
UPWORK_TOKEN_ENDPOINT = 'https://www.upwork.com/api/v3/oauth2/token'
UPWORK_GRAPHQL_URL = 'https://api.upwork.com/graphql'

# Upwork sits behind Cloudflare, which 403-blocks bot-like User-Agents (default
# 'Python-urllib/x' and even 'Mozilla/5.0 (compatible; ...)'). Use a real browser UA.
UPWORK_USER_AGENT = ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
                     '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')


def upwork_request(url, data=None, headers=None, timeout=30, proxy=None, method='POST'):
    """HTTP request to Upwork and return (status_code:int, body:str).

    Upwork is behind Cloudflare, which blocks by TLS fingerprint (JA3) AND by IP
    reputation. 'curl_cffi' (when installed) impersonates Chrome's TLS handshake to
    beat the fingerprint check; a `proxy` (clean/residential IP) beats the IP block
    — datacenter IPs (e.g. Hetzner/AWS) are frequently 403'd regardless of headers.
    `proxy` is an http(s)/socks5(h) proxy URL; pass None to go direct. curl_cffi
    handles SOCKS5; the urllib fallback only supports http/https proxies.
    """
    hdrs = {'User-Agent': UPWORK_USER_AGENT, 'Accept-Language': 'en-US,en;q=0.9'}
    hdrs.update(headers or {})
    proxies = {'http': proxy, 'https': proxy} if proxy else None
    try:
        from curl_cffi import requests as _cffi
    except ImportError:
        _cffi = None
    if _cffi is not None:
        resp = _cffi.request(method, url, data=data, headers=hdrs, timeout=timeout,
                             impersonate='chrome', proxies=proxies)
        return resp.status_code, resp.text
    if proxies:
        handler = urllib.request.ProxyHandler(proxies)
        opener = urllib.request.build_opener(handler)
    else:
        opener = urllib.request.build_opener()
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with opener.open(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode(errors='replace')
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode(errors='replace')


def _socks5_proxy_url(raw):
    """Parse a 'HOST:PORT:USER:PASS' string (auth optional → 'HOST:PORT') into a
    'socks5h://[user:pass@]host:port' URL, or None if empty/malformed. socks5h
    resolves DNS at the proxy so the proxy's IP is what Upwork/Cloudflare sees."""
    raw = (raw or '').strip()
    if not raw:
        return None
    parts = raw.split(':', 3)  # keep ':' inside a password (the 4th field)
    if len(parts) < 2:
        return None
    host, port = parts[0].strip(), parts[1].strip()
    if not host or not port.isdigit():
        return None
    if len(parts) >= 4 and parts[2]:
        user = urllib.parse.quote(parts[2], safe='')
        password = urllib.parse.quote(parts[3], safe='')
        return 'socks5h://%s:%s@%s:%s' % (user, password, host, port)
    return 'socks5h://%s:%s' % (host, port)


def _upwork_proxy(env):
    """Outbound proxy (clean IP) for Upwork calls — needed because Cloudflare
    IP-blocks this server's datacenter IP. Prefers the SOCKS5 proxy configured on
    the Upwork settings; falls back to the 'upwork.proxy_url' system parameter."""
    cfg = env['usa.settings'].sudo()._get_singleton()
    url = _socks5_proxy_url(cfg.socks5_proxy)
    if url:
        return url
    return (env['ir.config_parameter'].sudo().get_param('upwork.proxy_url') or '').strip() or None

QUERY_COMPANY_SELECTOR = """
{
  companySelector {
    items {
      title
      photoUrl
      organizationId
      organizationRid
      organizationType
    }
  }
}
"""

QUERY_ACCOUNTING_ENTITY = """
{
  accountingEntity {
    id
  }
}
"""

QUERY_TRANSACTION_HISTORY = """
{
  transactionHistory(transactionHistoryFilter: {
    transactionDateTime_bt: {
      rangeStart: "%s",
      rangeEnd: "%s",
    }
    aceIds_any: [%s]
  }) {
    transactionDetail {
      transactionHistoryRow {
        rowNumber
        runningChargeableBalance { rawValue currency displayValue }
        recordId
        remainder
        amountCreditedToUser { rawValue currency displayValue }
        transactionReviewDueDate
        transactionCreationDate
        relatedUserPaymentMethod
        accountingSubtype
        descriptionUI
        relatedAssignment
        amountSentInOrigCurrency { rawValue currency displayValue }
        paymentGuaranteed
        fixedPriceEARMark
        relatedTransactionId
        relatedInvoiceId
        fullyPaidDate
        type
        transactionAmount { rawValue currency displayValue }
        relatedAccountingEntity
        description
        purchaseOrderNumber
        assignmentAgencyName
        assignmentCompanyName
        assignmentDeveloperName
        assignmentTeamCompanyId
        assignmentTeamCompanyReference
        assignmentTeamId
        assignmentTeamReference
        assignmentTeamUserId
        assignmentTeamUserReference
        payment { rawValue currency displayValue }
        paymentStatus
        prefix
      }
    }
  }
}
"""


# ── Default accounting setup data (dedicated 6-digit Upwork chart) ────────────
# (code, name, account_type)
UPWORK_ACCOUNT_SET = [
    ('101410', 'Upwork Wallet – USD', 'asset_cash'),
    ('101710', 'Upwork Cash in Transit', 'asset_current'),
    ('101720', 'Upwork Funding (clearing)', 'asset_current'),
    ('131500', 'Upwork Input VAT (recoverable)', 'asset_current'),
    ('400500', 'Upwork Revenue – Hourly', 'income'),
    ('400510', 'Upwork Revenue – Fixed Price', 'income'),
    ('400590', 'Upwork Sales Refunds', 'income'),
    ('450500', 'Upwork Bonus / Tips', 'income_other'),
    ('450510', 'Upwork Reimbursed Expenses', 'income_other'),
    ('450520', 'Upwork Other Revenue', 'income_other'),
    ('600500', 'Upwork Service Fees', 'expense'),
    ('600510', 'Upwork Membership & Connects', 'expense'),
    ('600520', 'Upwork Withdrawal / Bank Fees', 'expense'),
]
# (transaction_type, accounting_subtype, account_code, label, posting_mode)
#   customer_invoice / vendor_bill → bank line to suspense, P&L via the document
#   gl                             → bank line posts straight to the account
UPWORK_SEED_RULES = [
    ('APInvoice', 'Hourly', '400500', 'Hourly revenue', 'customer_invoice'),
    ('APInvoice', 'Fixed Price', '400510', 'Fixed-price revenue', 'customer_invoice'),
    ('APInvoice', 'Miscellaneous', '450520', 'Other revenue', 'gl'),
    ('APAdjustment', 'Milestone', '400510', 'Milestone revenue', 'customer_invoice'),
    ('APAdjustment', 'Bonus', '450500', 'Bonus / tip', 'customer_invoice'),
    ('APAdjustment', 'Expense', '450510', 'Reimbursed expense', 'gl'),
    ('APAdjustment', 'Service Fee', '600500', 'Service fee', 'vendor_bill'),
    ('APAdjustment', 'Withdrawal Fee', '600520', 'Withdrawal fee', 'gl'),
    ('APAdjustment', 'Refund', '400590', 'Refund to client', 'customer_refund'),
    ('ARInvoice', 'Membership Fee', '600510', 'Membership / Connects', 'vendor_bill'),
    ('ARInvoice', 'VAT', '131500', 'Input VAT', 'gl'),
    ('APPayment', 'Withdrawal', '101710', 'Withdrawal to bank (in transit)', 'gl'),
    ('ARPayment', 'Payment', '101720', 'Card / external funding (clearing)', 'gl'),
]


class UsaSettings(models.Model):
    """Singleton configuration record for Upwork Simple Accounting integration."""

    _name = 'usa.settings'
    _description = 'Upwork Simple Accounting Settings'
    _inherit = ['mail.thread']

    lock_field = fields.Char(default='global', copy=False)

    _sql_constraints = [
        (
            'singleton',
            'UNIQUE(lock_field)',
            'Only one Upwork settings record is allowed.',
        ),
    ]

    # ── OAuth / API Credentials ───────────────────────────────────────────────

    upwork_key = fields.Char(
        string='API Key (Client ID)',
        copy=False,
        tracking=True,
    )
    upwork_secret = fields.Char(
        string='API Secret (Client Secret)',
        copy=False,
    )
    callback_url = fields.Char(
        string='Callback URL for OAuth',
        compute='_compute_callback_url',
        help='Always derived live from the Odoo base URL (web.base.url). '
             'Not stored, so it stays correct across DB restores and domain changes.',
    )
    access_token = fields.Char(string='Access Token', copy=False)
    refresh_token = fields.Char(string='Refresh Token', copy=False)
    token_expiry = fields.Datetime(string='Token Expiry', copy=False, readonly=True)
    oauth_state = fields.Selection(
        selection=[
            ('not_connected', 'Not Connected'),
            ('connected', 'Connected'),
        ],
        string='Connection Status',
        compute='_compute_oauth_state',
        store=False,
    )
    socks5_proxy = fields.Char(
        string='SOCKS5 Proxy (HOST:PORT:USER:PASS)',
        copy=False,
        help='Routes ONLY Upwork API calls through this SOCKS5 proxy — needed '
             'because Cloudflare IP-blocks this server. Format HOST:PORT:USER:PASS '
             '(auth optional → HOST:PORT). Requires curl_cffi.',
    )

    # ── Organization ─────────────────────────────────────────────────────────

    selected_organization_id = fields.Many2one(
        'usa.organization',
        string='Organization',
        ondelete='set null',
        tracking=True,
    )
    accounting_entity_id = fields.Char(
        string='Accounting Entity ID',
        readonly=True,
        copy=False,
    )

    # ── Accounting Injection ────────────────────────────────────────────────
    journal_id = fields.Many2one(
        'account.journal', string='Odoo Bank Journal',
        domain="[('type', '=', 'bank')]",
        help='Bank journal where Upwork transactions will be injected as statement lines.',
    )
    upwork_wallet_account_id = fields.Many2one(
        'account.account', string='Upwork Wallet Account',
        domain="[('deprecated', '=', False)]",
        help='The Upwork balance ("Upwork Bank") — the bank journal default account.',
    )
    default_counterpart_account_id = fields.Many2one(
        'account.account', string='Fallback GL Account',
        domain="[('deprecated', '=', False)]",
        help='Counterpart used when no mapping rule matches an injected transaction. '
             'If empty, the line falls back to the journal suspense account.',
    )
    account_mapping_ids = fields.One2many(
        'usa.account.map', 'config_id', string='Injection Rules',
    )
    auto_enrich_clients = fields.Boolean(
        string='Auto-enrich new clients from invoices', default=False,
        help='When a customer invoice is created for a client whose partner card '
             'has no address, queue an AI extraction to fill street/zip/country '
             '(runs at most once per client).',
    )

    # ── Ledger Sync ───────────────────────────────────────────────────────────

    def _default_sync_date_start(self):
        """Latest transaction date minus 2 weeks, falling back to Jan 1 of current year."""
        latest = self.env['usa.transaction'].sudo().search(
            [('transaction_creation_date', '!=', False)],
            order='transaction_creation_date desc',
            limit=1,
        )
        if latest:
            return (latest.transaction_creation_date - timedelta(weeks=2)).date()
        return fields.Date.today().replace(month=1, day=1)

    sync_date_start = fields.Date(
        string='Period Start',
        default=_default_sync_date_start,
    )
    sync_date_end = fields.Date(
        string='Period End',
        default=fields.Date.today,
    )
    last_sync_date = fields.Datetime(
        string='Last Synced',
        readonly=True,
        copy=False,
    )
    transaction_count = fields.Integer(
        string='Transactions in Database',
        compute='_compute_transaction_stats',
    )
    oldest_transaction_date = fields.Datetime(
        string='Oldest Transaction',
        compute='_compute_transaction_stats',
    )
    latest_transaction_date = fields.Datetime(
        string='Latest Transaction',
        compute='_compute_transaction_stats',
    )

    # ── Computed ──────────────────────────────────────────────────────────────

    @api.depends('access_token')
    def _compute_oauth_state(self):
        for rec in self:
            rec.oauth_state = 'connected' if rec.sudo().access_token else 'not_connected'

    @api.depends()
    def _compute_callback_url(self):
        # Non-stored: recomputed on every read so the redirect_uri always matches
        # the instance's current public domain, never a stale value from a DB restore.
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '').rstrip('/')
        for rec in self:
            rec.callback_url = '%s/upwork/callback' % base_url

    def _compute_transaction_stats(self):
        Transaction = self.env['usa.transaction'].sudo()
        count = Transaction.search_count([])
        oldest = Transaction.search(
            [('transaction_creation_date', '!=', False)],
            order='transaction_creation_date asc', limit=1,
        )
        latest = Transaction.search(
            [('transaction_creation_date', '!=', False)],
            order='transaction_creation_date desc', limit=1,
        )
        for rec in self:
            rec.transaction_count = count
            rec.oldest_transaction_date = oldest.transaction_creation_date if oldest else False
            rec.latest_transaction_date = latest.transaction_creation_date if latest else False

    # ── Singleton helpers ─────────────────────────────────────────────────────

    @api.model
    def _get_singleton(self):
        """Return the singleton record, creating it if needed."""
        record = self.sudo().search([], limit=1)
        if not record:
            record = self.sudo().create({})
        return record

    @api.model
    def action_open_settings(self):
        """Open the Upwork Configuration standalone form."""
        record = self._get_singleton()
        view_id = self.env.ref(
            'upwork_simple_accounting_integration.view_usa_settings_upwork_form').id
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'usa.settings',
            'res_id': record.id,
            'view_mode': 'form',
            'view_id': view_id,
            'target': 'current',
        }

    @api.model
    def action_open_ledger(self):
        """Open the Transaction Sync standalone form."""
        record = self._get_singleton()
        view_id = self.env.ref(
            'upwork_simple_accounting_integration.view_usa_settings_ledger_form').id
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'usa.settings',
            'res_id': record.id,
            'view_mode': 'form',
            'view_id': view_id,
            'target': 'current',
        }

    @api.model
    def action_open_accounting_mapping(self):
        """Open the Accounting Mapping standalone form."""
        record = self._get_singleton()
        view_id = self.env.ref(
            'upwork_simple_accounting_integration.view_usa_settings_accounting_form').id
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'usa.settings',
            'res_id': record.id,
            'view_mode': 'form',
            'view_id': view_id,
            'target': 'current',
        }

    # ── Accounting setup & mapping ────────────────────────────────────────────

    def _match_rule(self, tx):
        """Return the usa.account.map rule matching tx (exact subtype → type
        wildcard), or an empty recordset."""
        self.ensure_one()
        company = self.journal_id.company_id or self.env.company
        Map = self.env['usa.account.map'].sudo()
        ttype = (tx.transaction_type or '').strip()
        subtype = (tx.accounting_subtype or '').strip()
        base = [('company_id', '=', company.id), ('transaction_type', '=', ttype)]
        rule = Map.search(base + [('accounting_subtype', '=', subtype)], limit=1)
        if not rule:
            rule = Map.search(base + [('accounting_subtype', 'in', (False, ''))], limit=1)
        return rule

    def _is_card_paid_membership(self, tx):
        """True for a Connects/Membership charge funded by an external card (it has a
        linked 'Paid from card' ARPayment). The funding source is ambiguous — corporate
        card (match to the card statement) vs personal/director card (not a company
        expense) — so these are parked in the card clearing/suspense account for manual
        handling instead of being auto-booked as a vendor bill. Balance-paid memberships
        (no linked ARPayment) are unaffected and keep becoming vendor bills."""
        if tx.transaction_type != 'ARInvoice' or tx.accounting_subtype != 'Membership Fee':
            return False
        return bool(self.env['usa.transaction'].sudo().search_count([
            ('transaction_type', '=', 'ARPayment'),
            ('related_transaction_id', '=', tx.record_id),
        ]))

    def _card_suspense_account(self):
        """The account card-paid memberships are parked in: the one mapped to
        ARPayment/Payment (the card clearing/suspense, e.g. 101720), so the charge and
        its card receipt land in the same account and net there pending reclassification."""
        self.ensure_one()
        company = self.journal_id.company_id or self.env.company
        rule = self.env['usa.account.map'].sudo().search([
            ('company_id', '=', company.id),
            ('transaction_type', '=', 'ARPayment'),
            ('accounting_subtype', '=', 'Payment'),
        ], limit=1)
        return rule.account_id if rule else self.default_counterpart_account_id

    def _get_account_for_transaction(self, tx):
        """Counterpart GL account for a usa.transaction (mapped rule → settings
        fallback → empty so Odoo uses the journal suspense account)."""
        self.ensure_one()
        if self._is_card_paid_membership(tx):
            return self._card_suspense_account()
        rule = self._match_rule(tx)
        return rule.account_id if rule else self.default_counterpart_account_id

    def _get_posting_mode_for_transaction(self, tx):
        """Posting mode for a usa.transaction. Resolves the mapping rule, then flips
        invoice↔credit-note by the signed wallet amount (a positive Service Fee is a
        'fee return' → vendor credit note; a negative revenue line → customer credit
        note). Returns one of: gl / customer_invoice / customer_refund /
        vendor_bill / vendor_refund."""
        self.ensure_one()
        # Card-paid Connects/Membership → park in suspense (GL), never a vendor bill.
        if self._is_card_paid_membership(tx):
            return 'gl'
        rule = self._match_rule(tx)
        mode = rule.posting_mode if rule else 'gl'
        amt = tx.amount_credited_raw or tx.transaction_amount_raw or 0.0
        if mode == 'vendor_bill' and amt > 0:
            mode = 'vendor_refund'
        elif mode == 'customer_invoice' and amt < 0:
            mode = 'customer_refund'
        return mode

    def _ensure_account(self, company, code, name, account_type):
        """Idempotently get-or-create an account by (company, code).

        If an account with that code already exists it is reused as-is (a type
        mismatch is logged, never overwritten) to respect the company's chart.
        """
        Account = self.env['account.account'].sudo()
        account = Account.search(
            [('company_id', '=', company.id), ('code', '=', code)], limit=1)
        if account:
            if account.account_type != account_type:
                _logger.warning(
                    "Upwork setup: account %s (%s) exists with type %s; expected %s — "
                    "reusing without changes.",
                    code, account.name, account.account_type, account_type)
            return account
        return Account.create({
            'code': code,
            'name': name,
            'account_type': account_type,
            'company_id': company.id,
        })

    def action_setup_upwork_accounting(self):
        """One-click idempotent setup: create the dedicated Upwork chart of accounts,
        the Upwork Wallet (USD) bank journal, and seed the subtype → account rules."""
        self.ensure_one()
        company = self.env.company

        accounts = {
            code: self._ensure_account(company, code, name, atype)
            for code, name, atype in UPWORK_ACCOUNT_SET
        }
        wallet = accounts['101410']

        # Upwork Wallet bank journal (idempotent by code)
        Journal = self.env['account.journal'].sudo()
        journal = Journal.search(
            [('company_id', '=', company.id), ('type', '=', 'bank'),
             ('code', '=', 'UPWK')], limit=1)
        usd = self.env['res.currency'].with_context(active_test=False).search(
            [('name', '=', 'USD')], limit=1)
        if usd and not usd.active:
            usd.sudo().active = True
        if not journal:
            journal = Journal.create({
                'name': 'Upwork Wallet (USD)',
                'code': 'UPWK',
                'type': 'bank',
                'company_id': company.id,
                'currency_id': usd.id if usd else False,
                'default_account_id': wallet.id,
            })
        elif not journal.default_account_id:
            journal.default_account_id = wallet.id

        # Seed mapping rules (upsert on key; never clobber a user-set account)
        Map = self.env['usa.account.map'].sudo()
        for ttype, subtype, code, label, mode in UPWORK_SEED_RULES:
            existing = Map.search([
                ('company_id', '=', company.id),
                ('transaction_type', '=', ttype),
                ('accounting_subtype', '=', subtype),
            ], limit=1)
            vals = {
                'config_id': self.id,
                'company_id': company.id,
                'transaction_type': ttype,
                'accounting_subtype': subtype,
                'account_id': accounts[code].id,
                'label': label,
                'posting_mode': mode,
            }
            if existing:
                update = {}
                if not existing.account_id:
                    update.update(vals)
                # Keep default (un-customised) rules' posting_mode aligned to the seed.
                elif existing.account_id.id == accounts[code].id and existing.posting_mode != mode:
                    update['posting_mode'] = mode
                if update:
                    existing.write(update)
            else:
                Map.create(vals)

        self.write({
            'journal_id': journal.id,
            'upwork_wallet_account_id': wallet.id,
            'default_counterpart_account_id': accounts['450520'].id,
        })

        # Reporting ring-fence: the "Data Source" analytic plan + "Upwork" account
        # stamped on every Upwork move line (see account.move._post).
        self._ensure_upwork_analytic()

        view_id = self.env.ref(
            'upwork_simple_accounting_integration.view_usa_settings_accounting_form').id
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'usa.settings',
            'res_id': self.id,
            'view_mode': 'form',
            'view_id': view_id,
            'target': 'current',
        }

    # ── OAuth Actions ─────────────────────────────────────────────────────────

    def action_check_proxy(self):
        """Test the configured SOCKS5 proxy: show the egress IP Upwork would see,
        and confirm Upwork is reachable through it (past Cloudflare)."""
        self.ensure_one()
        proxy = _socks5_proxy_url(self.socks5_proxy)
        if not proxy:
            raise UserError(_(
                'No valid SOCKS5 proxy configured. Use the format '
                'HOST:PORT:USER:PASS (auth optional → HOST:PORT).'))

        # 1) Egress IP through the proxy (best-effort).
        egress_ip = '?'
        try:
            s, body = upwork_request('https://api.ipify.org', method='GET',
                                     timeout=15, proxy=proxy)
            if s == 200 and body.strip():
                egress_ip = body.strip()[:64]
        except Exception:  # noqa: BLE001
            pass

        # 2) Reach Upwork through the proxy (decisive): a junk token POST. If we get
        #    past Cloudflare, Upwork returns a 400/401 OAuth error (not its block page).
        try:
            dummy = urllib.parse.urlencode({
                'grant_type': 'authorization_code', 'code': 'x'}).encode()
            status, body = upwork_request(
                UPWORK_TOKEN_ENDPOINT, dummy,
                headers={'Content-Type': 'application/x-www-form-urlencoded',
                         'Accept': 'application/json'},
                timeout=20, proxy=proxy)
        except Exception as exc:  # noqa: BLE001
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Check proxy connectivity'),
                    'message': _('Proxy connection failed: %s') % str(exc)[:200],
                    'type': 'danger',
                    'sticky': True,
                },
            }

        blocked = 'Attention Required' in body or 'cloudflare' in body.lower()
        if blocked:
            msg = _('Proxy connects (egress IP %(ip)s) but Upwork is STILL '
                    'Cloudflare-blocked (HTTP %(s)s). Try a different proxy IP.') % {
                'ip': egress_ip, 's': status}
            notif_type = 'warning'
        else:
            msg = _('Proxy OK — egress IP %(ip)s; Upwork reachable past Cloudflare '
                    '(HTTP %(s)s).') % {'ip': egress_ip, 's': status}
            notif_type = 'success'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Check proxy connectivity'),
                'message': msg,
                'type': notif_type,
                'sticky': blocked,
            },
        }

    def action_connect_upwork(self):
        """Build the Upwork OAuth2 authorization URL and open it in a new tab."""
        self.ensure_one()
        if not self.upwork_key:
            raise UserError(_('Please enter the Upwork API Key (Client ID) first.'))
        if not self.callback_url:
            raise UserError(_('Callback URL is not set.'))
        auth_url = (
            '%s?client_id=%s&redirect_uri=%s&response_type=code'
            % (
                UPWORK_AUTH_URL,
                urllib.parse.quote(self.upwork_key, safe=''),
                urllib.parse.quote(self.callback_url, safe=''),
            )
        )
        return {
            'type': 'ir.actions.act_url',
            'url': auth_url,
            'target': 'new',
        }

    def action_disconnect(self):
        """Clear OAuth tokens and disconnect from Upwork."""
        self.ensure_one()
        self.sudo().write({
            'access_token': False,
            'refresh_token': False,
            'token_expiry': False,
            'selected_organization_id': False,
            'accounting_entity_id': False,
        })
        view_id = self.env.ref(
            'upwork_simple_accounting_integration.view_usa_settings_upwork_form').id
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'usa.settings',
            'res_id': self.id,
            'view_mode': 'form',
            'view_id': view_id,
            'target': 'current',
        }

    # ── Token management ──────────────────────────────────────────────────────

    def _is_token_valid(self):
        self.ensure_one()
        return (
            self.sudo().token_expiry
            and self.sudo().token_expiry >= (fields.Datetime.now() + timedelta(minutes=1))
        )

    def _refresh_access_token(self):
        """Silently refresh the access token using the stored refresh token."""
        self.ensure_one()
        refresh_token = self.sudo().refresh_token
        if not refresh_token:
            raise UserError(_(
                'No refresh token available. Please reconnect your Upwork account.'
            ))

        post_data = urllib.parse.urlencode({
            'refresh_token': refresh_token,
            'client_id': self.upwork_key or '',
            'client_secret': self.sudo().upwork_secret or '',
            'grant_type': 'refresh_token',
        }).encode()

        try:
            status, body = upwork_request(
                UPWORK_TOKEN_ENDPOINT, post_data,
                headers={'Content-Type': 'application/x-www-form-urlencoded',
                         'Accept': 'application/json'},
                timeout=20, proxy=_upwork_proxy(self.env))
        except Exception as exc:
            raise UserError(_('Failed to refresh Upwork access token: %s', str(exc)))
        if status != 200:
            try:
                err = json.loads(body).get('error_description', body)
            except Exception:
                err = body[:300]
            if status in (400, 401):
                self.sudo().write({
                    'access_token': False,
                    'refresh_token': False,
                    'token_expiry': False,
                })
            raise UserError(_('Failed to refresh Upwork access token (HTTP %s): %s', status, err))
        try:
            data = json.loads(body)
        except Exception:
            raise UserError(_('Upwork returned a non-JSON token response: %s', body[:300]))

        ttl = data.get('expires_in', 3600)
        self.sudo().write({
            'access_token': data.get('access_token'),
            'token_expiry': fields.Datetime.now() + timedelta(seconds=int(ttl)),
        })

    def _get_valid_access_token(self):
        """Return a valid access token, refreshing if needed."""
        self.ensure_one()
        if not self.sudo().access_token:
            raise UserError(_(
                'Upwork account is not connected. '
                'Please go to Configuration → Upwork Configuration and connect.'
            ))
        if not self._is_token_valid():
            self._refresh_access_token()
        return self.sudo().access_token

    # ── GraphQL helper ────────────────────────────────────────────────────────

    def _graphql_query(self, query, tenant_id=None):
        """Execute a GraphQL query against the Upwork API.

        Returns the parsed JSON response dict.
        Raises UserError on HTTP or API errors.
        """
        self.ensure_one()
        token = self._get_valid_access_token()
        headers = {
            'Authorization': 'Bearer %s' % token,
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': UPWORK_USER_AGENT,
        }
        if tenant_id:
            headers['X-Upwork-API-TenantId'] = str(tenant_id)

        payload = json.dumps({'query': query}).encode()
        try:
            status, body = upwork_request(UPWORK_GRAPHQL_URL, payload, headers=headers, timeout=30, proxy=_upwork_proxy(self.env))
        except Exception as exc:
            raise UserError(_('Upwork API request failed: %s', str(exc)))
        if status != 200:
            _logger.error("Upwork GraphQL HTTP error %s: %s", status, body[:500])
            raise UserError(_('Upwork API error %s: %s', status, body[:300]))
        try:
            result = json.loads(body)
        except Exception:
            raise UserError(_('Upwork API returned a non-JSON response: %s', body[:300]))

        if result.get('errors'):
            msgs = '; '.join(e.get('message', str(e)) for e in result['errors'])
            raise UserError(_('Upwork GraphQL error: %s', msgs))
        return result

    # ── Organization actions ──────────────────────────────────────────────────

    def action_load_organizations(self):
        """Fetch organizations from Upwork companySelector and populate the dropdown.

        After refreshing the list the accounting entity is resolved automatically:
        - Single org  → auto-selected, entity loaded.
        - Multiple orgs, previously selected org still present → re-selected, entity reloaded.
        - Multiple orgs, no previous selection → user picks from dropdown (onchange loads entity).
        """
        self.ensure_one()
        result = self._graphql_query(QUERY_COMPANY_SELECTOR)
        items = (
            result.get('data', {})
            .get('companySelector', {})
            .get('items', [])
        )
        if not items:
            raise UserError(_('No organizations returned from Upwork API.'))

        # Remember which org was selected before we wipe the list (ondelete='set null')
        prev_org_external_id = (
            self.selected_organization_id.organization_id
            if self.selected_organization_id else None
        )

        # Sync organizations: delete all and recreate from API response
        self.env['usa.organization'].sudo().search([]).unlink()
        orgs = []
        for item in items:
            org = self.env['usa.organization'].sudo().create({
                'title': item.get('title') or '',
                'organization_id': item.get('organizationId') or '',
                'organization_rid': item.get('organizationRid') or '',
                'organization_type': item.get('organizationType') or '',
                'photo_url': item.get('photoUrl') or '',
            })
            orgs.append(org)

        # Determine which org to auto-select
        if len(orgs) == 1:
            target_org = orgs[0]
        elif prev_org_external_id:
            target_org = next(
                (o for o in orgs if o.organization_id == prev_org_external_id), None)
        else:
            target_org = None

        if target_org:
            write_vals = {'selected_organization_id': target_org.id}
            try:
                ae_result = self._graphql_query(
                    QUERY_ACCOUNTING_ENTITY, tenant_id=target_org.organization_id)
                entity_id = (
                    ae_result.get('data', {})
                    .get('accountingEntity', {})
                    .get('id')
                )
                write_vals['accounting_entity_id'] = str(entity_id) if entity_id else False
            except Exception as exc:
                _logger.warning("Could not auto-load accounting entity: %s", exc)
            self.sudo().write(write_vals)

        view_id = self.env.ref(
            'upwork_simple_accounting_integration.view_usa_settings_upwork_form').id
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'usa.settings',
            'res_id': self.id,
            'view_mode': 'form',
            'view_id': view_id,
            'target': 'current',
        }

    @api.onchange('selected_organization_id')
    def _onchange_selected_organization(self):
        """Load accounting entity and persist both fields immediately.

        Writing via self._origin means the user never needs to click Save —
        selecting a different organization in the dropdown is sufficient.
        """
        origin = self._origin
        if not self.selected_organization_id:
            self.accounting_entity_id = False
            if origin.exists():
                origin.sudo().write({
                    'selected_organization_id': False,
                    'accounting_entity_id': False,
                })
            return
        if not self.sudo().access_token:
            return
        try:
            org_id = self.selected_organization_id.organization_id
            result = self._graphql_query(QUERY_ACCOUNTING_ENTITY, tenant_id=org_id)
            entity_id = (
                result.get('data', {})
                .get('accountingEntity', {})
                .get('id')
            )
            entity_str = str(entity_id) if entity_id else False
            self.accounting_entity_id = entity_str
            # Persist immediately — no manual Save required
            if origin.exists():
                origin.sudo().write({
                    'selected_organization_id': self.selected_organization_id.id,
                    'accounting_entity_id': entity_str,
                })
        except Exception as exc:
            _logger.warning("Could not auto-load accounting entity: %s", exc)
            self.accounting_entity_id = False
            return {'warning': {
                'title': _('Could not load Accounting Entity'),
                'message': str(exc),
            }}

    # ── Transaction sync ──────────────────────────────────────────────────────

    def action_sync_transactions(self):
        """Download all transactions for the configured period and accounting entity."""
        self.ensure_one()
        if not self.accounting_entity_id:
            raise UserError(_(
                'No accounting entity configured. '
                'Please select an organization first.'
            ))
        if not self.sync_date_start or not self.sync_date_end:
            raise UserError(_('Please set Period Start and Period End before syncing.'))

        period_start = '%sT00:00:00+00:00' % self.sync_date_start.strftime('%Y-%m-%d')
        period_end = '%sT23:59:59+00:00' % self.sync_date_end.strftime('%Y-%m-%d')
        ace_id = self.accounting_entity_id

        query = QUERY_TRANSACTION_HISTORY % (period_start, period_end, ace_id)
        org_id = (
            self.selected_organization_id.organization_id
            if self.selected_organization_id
            else None
        )
        result = self._graphql_query(query, tenant_id=org_id)

        rows = (
            result.get('data', {})
            .get('transactionHistory', {})
            .get('transactionDetail', {})
            .get('transactionHistoryRow', [])
        )

        created = 0
        updated = 0
        Transaction = self.env['usa.transaction'].sudo()

        for row in rows:
            vals = self._map_transaction_row(row)
            record_id = vals.get('record_id')
            if not record_id:
                continue
            existing = Transaction.search([('record_id', '=', record_id)], limit=1)
            if existing:
                existing.write(vals)
                updated += 1
            else:
                Transaction.create(vals)
                created += 1

        self.sudo().write({'last_sync_date': fields.Datetime.now()})

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Sync Complete'),
                'message': _('Synced %d transactions (%d new, %d updated).', len(rows), created, updated),
                'type': 'success',
                'sticky': False,
            },
        }

    def _map_transaction_row(self, row):
        """Map a transactionHistoryRow dict to usa.transaction field values."""

        def _money_raw(obj):
            if not obj:
                return 0.0
            try:
                return float(obj.get('rawValue') or 0)
            except (ValueError, TypeError):
                return 0.0

        def _money_currency(obj):
            if not obj:
                return ''
            return obj.get('currency') or ''

        def _dt(val):
            if not val:
                return False
            # Upwork returns ISO8601: '2025-12-31T00:00:00+0000'
            from datetime import datetime, timezone
            import re
            # Normalize offset format +0000 → +00:00
            val_norm = re.sub(r'([+-]\d{2})(\d{2})$', r'\1:\2', val)
            try:
                dt = datetime.fromisoformat(val_norm)
                return dt.astimezone(timezone.utc).replace(tzinfo=None)
            except Exception:
                return False

        return {
            'record_id': str(row.get('recordId') or ''),
            'row_number': int(row.get('rowNumber') or 0),
            'transaction_creation_date': _dt(row.get('transactionCreationDate')),
            'transaction_review_due_date': _dt(row.get('transactionReviewDueDate')),
            'fully_paid_date': _dt(row.get('fullyPaidDate')),
            'transaction_type': row.get('type') or '',
            'accounting_subtype': row.get('accountingSubtype') or '',
            'payment_status': row.get('paymentStatus') or '',
            'payment_guaranteed': bool(row.get('paymentGuaranteed')),
            'prefix': row.get('prefix') or '',
            'transaction_amount_raw': _money_raw(row.get('transactionAmount')),
            'transaction_amount_currency': _money_currency(row.get('transactionAmount')),
            'amount_credited_raw': _money_raw(row.get('amountCreditedToUser')),
            'amount_credited_currency': _money_currency(row.get('amountCreditedToUser')),
            'running_balance_raw': _money_raw(row.get('runningChargeableBalance')),
            'running_balance_currency': _money_currency(row.get('runningChargeableBalance')),
            'amount_sent_orig_raw': _money_raw(row.get('amountSentInOrigCurrency')),
            'amount_sent_orig_currency': _money_currency(row.get('amountSentInOrigCurrency')),
            'payment_raw': _money_raw(row.get('payment')),
            'payment_currency': _money_currency(row.get('payment')),
            'remainder': str(row.get('remainder') or ''),
            'description': row.get('description') or '',
            'description_ui': row.get('descriptionUI') or '',
            'purchase_order_number': row.get('purchaseOrderNumber') or '',
            'related_transaction_id': str(row.get('relatedTransactionId') or ''),
            'related_invoice_id': str(row.get('relatedInvoiceId') or ''),
            'related_assignment': str(row.get('relatedAssignment') or ''),
            'related_accounting_entity': str(row.get('relatedAccountingEntity') or ''),
            'related_user_payment_method': str(row.get('relatedUserPaymentMethod') or ''),
            'fixed_price_earmark': str(row.get('fixedPriceEARMark') or ''),
            'assignment_agency_name': row.get('assignmentAgencyName') or '',
            'assignment_company_name': row.get('assignmentCompanyName') or '',
            'assignment_developer_name': row.get('assignmentDeveloperName') or '',
            'assignment_team_id': str(row.get('assignmentTeamId') or ''),
            'assignment_team_reference': str(row.get('assignmentTeamReference') or ''),
            'assignment_team_company_id': str(row.get('assignmentTeamCompanyId') or ''),
            'assignment_team_company_reference': str(row.get('assignmentTeamCompanyReference') or ''),
            'assignment_team_user_id': str(row.get('assignmentTeamUserId') or ''),
            'assignment_team_user_reference': str(row.get('assignmentTeamUserReference') or ''),
            'raw_json': json.dumps(row, default=str, indent=2),
            'sync_date': fields.Datetime.now(),
        }

    def action_open_transactions(self):
        """Open the transaction list view."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Upwork Transactions'),
            'res_model': 'usa.transaction',
            'view_mode': 'tree,form',
            'target': 'current',
        }

    def action_set_sync_end_today(self):
        """Set Period End to today."""
        self.ensure_one()
        self.sudo().write({'sync_date_end': fields.Date.today()})
        view_id = self.env.ref(
            'upwork_simple_accounting_integration.view_usa_settings_ledger_form').id
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'usa.settings',
            'res_id': self.id,
            'view_mode': 'form',
            'view_id': view_id,
            'target': 'current',
        }

    def action_reset_sync_start(self):
        """Reset Period Start to latest transaction date minus 2 weeks."""
        self.ensure_one()
        latest = self.env['usa.transaction'].sudo().search(
            [('transaction_creation_date', '!=', False)],
            order='transaction_creation_date desc',
            limit=1,
        )
        if latest:
            start = (latest.transaction_creation_date - timedelta(weeks=2)).date()
        else:
            start = fields.Date.today().replace(month=1, day=1)
        self.sudo().write({'sync_date_start': start})
        view_id = self.env.ref(
            'upwork_simple_accounting_integration.view_usa_settings_ledger_form').id
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'usa.settings',
            'res_id': self.id,
            'view_mode': 'form',
            'view_id': view_id,
            'target': 'current',
        }


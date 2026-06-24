import base64
import datetime
import json
import logging
import os
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class LegacyAccountingConfig(models.Model):
    _name = 'legacy.accounting.config'
    _description = 'Legacy Accounting Helper - Revolut API Configuration'
    _rec_name = 'company_id'

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )

    # ── Timezone for accounting injection ────────────────────────────────────
    accounting_timezone = fields.Selection(
        '_get_timezone_selection',
        string='Accounting Timezone',
        default='UTC',
        help='Revolut provides UTC datetimes. When injecting into accounting, '
             'settlement dates are converted to this timezone.',
    )

    @api.model
    def _get_timezone_selection(self):
        """Return available timezones as selection list."""
        import pytz
        return [(tz, tz) for tz in sorted(pytz.common_timezones)]

    def write(self, vals):
        res = super().write(vals)
        if 'accounting_timezone' in vals:
            self._recompute_settlement_dates_local()
        return res

    def _recompute_settlement_dates_local(self):
        """Recompute settlement_date_local on all transactions for this company."""
        transactions = self.env['revolut.transaction'].sudo().search([
            ('company_id', '=', self.company_id.id),
        ])
        if transactions:
            transactions._compute_settlement_date_local()

    # ── Section 1: Certificates ──────────────────────────────────────────────

    private_cert_pem = fields.Text(string='Private Key (PEM)', readonly=True)
    public_cert_pem = fields.Text(string='Public Certificate (PEM)', readonly=True)
    public_ip = fields.Char(string='Public IP of This Machine', readonly=True)

    public_cert_binary = fields.Binary(
        string='Download Public Certificate',
        compute='_compute_public_cert_binary',
    )
    public_cert_fname = fields.Char(default='publiccert.cer')

    # ── Section 2: JWT ───────────────────────────────────────────────────────

    jwt_header = fields.Text(
        string='JWT Header',
        default='{\n  "alg": "RS256",\n  "typ": "JWT"\n}',
        readonly=True,
    )
    jwt_header_binary = fields.Binary(
        string='Download header.json',
        compute='_compute_jwt_header_binary',
    )
    jwt_header_fname = fields.Char(default='header.json')

    jwt_iss = fields.Char(
        string='iss — Issuer',
        help='Your server domain name, e.g. yourdomain.com. '
             'Must match the redirect URI you registered with Revolut.',
    )
    jwt_sub = fields.Char(
        string='sub — Client ID',
        help='Your Revolut Business client_id. '
             'Find it in Revolut Business → Settings → API.',
    )
    jwt_aud = fields.Char(
        string='aud — Audience',
        default='https://revolut.com',
        readonly=True,
    )
    jwt_exp_days = fields.Integer(string='Expiry (days)', default=90)
    jwt_exp_timestamp = fields.Integer(
        string='Expiry (UNIX timestamp)',
        compute='_compute_jwt_exp_timestamp',
    )
    jwt_payload = fields.Text(
        string='JWT Payload (JSON)',
        compute='_compute_jwt_payload',
    )

    client_assertion = fields.Text(string='Client Assertion (JWT)', readonly=True)
    client_assertion_binary = fields.Binary(
        string='Download client_assertion.txt',
        compute='_compute_client_assertion_binary',
    )
    client_assertion_fname = fields.Char(default='client_assertion.txt')

    # ── Section 3: Consent ───────────────────────────────────────────────────

    consent_url = fields.Char(
        string='Consent URL',
        compute='_compute_consent_url',
    )
    auth_code = fields.Char(
        string='Authorization Code',
        help='The value of the "code" query parameter from the redirect URL '
             'after the user approves access in Revolut Business.',
    )

    # ── Section 4: Token Exchange ────────────────────────────────────────────

    token_exchange_result = fields.Text(string='Token Exchange Response', readonly=True)
    access_token = fields.Char(string='Access Token', readonly=True)
    token_type = fields.Char(string='Token Type', readonly=True)
    expires_in = fields.Integer(string='Expires In (seconds)', readonly=True)
    refresh_token = fields.Char(string='Refresh Token', readonly=True)
    token_refresh_result = fields.Text(string='Token Refresh Response', readonly=True)
    token_obtained_at = fields.Datetime(string='Token Obtained At', readonly=True)
    token_expiry_display = fields.Char(
        string='Token Expires At',
        compute='_compute_token_expiry_display',
    )

    # ── Section 5: API Test ──────────────────────────────────────────────────

    api_test_result = fields.Text(string='API Test Response', readonly=True)

    # ── Revolut Account Mappings ─────────────────────────────────────────────

    account_mapping_ids = fields.One2many(
        'revolut.account.journal.map', 'config_id',
        string='Revolut Account Mappings',
    )

    # ── Progress tracking ────────────────────────────────────────────────────

    step1_complete = fields.Boolean(compute='_compute_step_status')
    step2_complete = fields.Boolean(compute='_compute_step_status')
    step3_complete = fields.Boolean(compute='_compute_step_status')
    step4_complete = fields.Boolean(compute='_compute_step_status')
    step5_complete = fields.Boolean(compute='_compute_step_status')

    # ── Computed field methods ───────────────────────────────────────────────

    @api.depends('public_cert_pem', 'private_cert_pem', 'client_assertion',
                 'auth_code', 'access_token', 'api_test_result')
    def _compute_step_status(self):
        for rec in self:
            rec.step1_complete = bool(rec.public_cert_pem and rec.private_cert_pem)
            rec.step2_complete = bool(rec.client_assertion)
            rec.step3_complete = bool(rec.auth_code)
            rec.step4_complete = bool(rec.access_token)
            rec.step5_complete = bool(rec.api_test_result)

    @api.depends('public_cert_pem')
    def _compute_public_cert_binary(self):
        for rec in self:
            if rec.public_cert_pem:
                rec.public_cert_binary = base64.b64encode(rec.public_cert_pem.encode())
            else:
                rec.public_cert_binary = False

    @api.depends('jwt_header')
    def _compute_jwt_header_binary(self):
        for rec in self:
            if rec.jwt_header:
                rec.jwt_header_binary = base64.b64encode(rec.jwt_header.encode())
            else:
                rec.jwt_header_binary = False

    @api.depends('jwt_exp_days')
    def _compute_jwt_exp_timestamp(self):
        for rec in self:
            days = rec.jwt_exp_days or 90
            future = datetime.datetime.utcnow() + datetime.timedelta(days=days)
            rec.jwt_exp_timestamp = int(future.timestamp())

    @api.depends('jwt_iss', 'jwt_sub', 'jwt_aud', 'jwt_exp_timestamp')
    def _compute_jwt_payload(self):
        for rec in self:
            payload = {
                "iss": rec.jwt_iss or "example.com",
                "sub": rec.jwt_sub or "zfTKV9Eie_XLHl03f2Y7vJYDe5Klr6Y54v8fsp4Gvgp",
                "aud": rec.jwt_aud or "https://revolut.com",
                "exp": rec.jwt_exp_timestamp or 1706136791,
            }
            rec.jwt_payload = json.dumps(payload, indent=2)

    @api.depends('client_assertion')
    def _compute_client_assertion_binary(self):
        for rec in self:
            if rec.client_assertion:
                rec.client_assertion_binary = base64.b64encode(rec.client_assertion.encode())
            else:
                rec.client_assertion_binary = False

    @api.depends('jwt_iss', 'jwt_sub')
    def _compute_consent_url(self):
        for rec in self:
            if rec.jwt_sub and rec.jwt_iss:
                rec.consent_url = (
                    f"https://business.revolut.com/app-confirm"
                    f"?client_id={rec.jwt_sub}"
                    f"&redirect_uri=https://{rec.jwt_iss}"
                    f"&response_type=code"
                )
            else:
                rec.consent_url = ""

    @api.depends('token_obtained_at', 'expires_in')
    def _compute_token_expiry_display(self):
        for rec in self:
            if rec.token_obtained_at and rec.expires_in:
                expiry = rec.token_obtained_at + datetime.timedelta(seconds=rec.expires_in)
                rec.token_expiry_display = expiry.strftime('%Y-%m-%d %H:%M UTC')
            else:
                rec.token_expiry_display = ''

    # ── Action methods ───────────────────────────────────────────────────────

    def action_generate_certificates(self):
        """Generate RSA 2048-bit private key + self-signed X.509 certificate via openssl."""
        with tempfile.TemporaryDirectory() as tmpdir:
            priv_path = os.path.join(tmpdir, 'privatecert.pem')
            pub_path = os.path.join(tmpdir, 'publiccert.cer')

            try:
                result = subprocess.run(
                    ['openssl', 'genrsa', '-out', priv_path, '2048'],
                    capture_output=True, text=True,
                )
                if result.returncode != 0:
                    raise UserError(
                        f'openssl genrsa failed:\n{result.stderr}'
                    )

                result = subprocess.run(
                    [
                        'openssl', 'req', '-new', '-x509',
                        '-key', priv_path,
                        '-out', pub_path,
                        '-days', '1825',
                        '-subj', '/CN=revolut-api',
                    ],
                    capture_output=True, text=True,
                )
                if result.returncode != 0:
                    raise UserError(
                        f'openssl req failed:\n{result.stderr}'
                    )

            except FileNotFoundError:
                raise UserError(
                    'openssl is not installed or not found in PATH. '
                    'Install it with: apt-get install openssl'
                )

            with open(priv_path) as f:
                self.private_cert_pem = f.read()
            with open(pub_path) as f:
                self.public_cert_pem = f.read()

        try:
            with urllib.request.urlopen('https://api.ipify.org', timeout=5) as resp:
                self.public_ip = resp.read().decode().strip()
        except Exception:
            self.public_ip = 'Unable to fetch (check network)'

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Certificates Generated',
                'message': 'RSA 2048-bit key and X.509 certificate created successfully via openssl.',
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    def action_generate_client_assertion(self):
        """Sign JWT payload with private key to produce a client_assertion."""
        if not self.private_cert_pem:
            raise UserError('Please generate certificates first (Step 1).')
        if not self.jwt_iss or not self.jwt_sub:
            raise UserError('Please fill in the iss and sub fields before generating the assertion.')

        try:
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.asymmetric import padding
            from cryptography.hazmat.primitives.serialization import load_pem_private_key
        except ImportError:
            raise UserError("The 'cryptography' Python package is required.")

        def _b64url(data):
            if isinstance(data, str):
                data = data.encode()
            return base64.urlsafe_b64encode(data).rstrip(b'=').decode()

        header = {"alg": "RS256", "typ": "JWT"}
        header_enc = _b64url(json.dumps(header, separators=(',', ':')))
        payload_enc = _b64url(self.jwt_payload)
        signing_input = f"{header_enc}.{payload_enc}"

        private_key = load_pem_private_key(self.private_cert_pem.encode(), password=None)
        sig = private_key.sign(signing_input.encode(), padding.PKCS1v15(), hashes.SHA256())
        self.client_assertion = f"{signing_input}.{_b64url(sig)}"

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Client Assertion Generated',
                'message': 'JWT signed successfully. Copy or download the value below.',
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    def action_exchange_token(self):
        """POST to Revolut token endpoint with authorization_code grant."""
        if not self.auth_code:
            raise UserError('Please enter the Authorization Code from Step 3.')
        if not self.client_assertion:
            raise UserError('Please generate a client_assertion first (Step 2).')

        url = 'https://b2b.revolut.com/api/1.0/auth/token'
        data = urllib.parse.urlencode({
            'grant_type': 'authorization_code',
            'code': self.auth_code,
            'client_assertion_type': 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer',
            'client_assertion': self.client_assertion,
        }).encode()

        try:
            req = urllib.request.Request(url, data=data, method='POST')
            req.add_header('Content-Type', 'application/x-www-form-urlencoded')
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode()
        except urllib.error.HTTPError as e:
            raw = e.read().decode()
        except Exception as e:
            raise UserError(f'Request failed: {e}')

        self.token_exchange_result = raw
        got_token = False
        try:
            parsed = json.loads(raw)
            token = parsed.get('access_token', '')
            if token:
                self.access_token = token
                self.token_type = parsed.get('token_type', '')
                self.expires_in = parsed.get('expires_in', 0)
                self.refresh_token = parsed.get('refresh_token', '')
                self.token_obtained_at = fields.Datetime.now()
                got_token = True
        except json.JSONDecodeError:
            pass

        if got_token:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Token Exchange Complete',
                    'message': 'Access token received and stored. See Token Details below.',
                    'type': 'success',
                    'sticky': False,
                    'next': {'type': 'ir.actions.act_window_close'},
                },
            }
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Token Exchange — No Token Received',
                'message': 'Response received but no access_token found. Check the raw response below.',
                'type': 'warning',
                'sticky': True,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    def action_refresh_token(self):
        """POST to Revolut token endpoint with refresh_token grant."""
        if not self.refresh_token:
            raise UserError('No refresh token available. Exchange an authorization code first.')
        if not self.client_assertion:
            raise UserError('Please generate a client_assertion first (Step 2).')

        url = 'https://b2b.revolut.com/api/1.0/auth/token'
        data = urllib.parse.urlencode({
            'grant_type': 'refresh_token',
            'refresh_token': self.refresh_token,
            'client_assertion_type': 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer',
            'client_assertion': self.client_assertion,
            'client_id': self.jwt_sub,
        }).encode()

        try:
            req = urllib.request.Request(url, data=data, method='POST')
            req.add_header('Content-Type', 'application/x-www-form-urlencoded')
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode()
        except urllib.error.HTTPError as e:
            raw = e.read().decode()
        except Exception as e:
            raise UserError(f'Request failed: {e}')

        self.token_refresh_result = raw
        try:
            parsed = json.loads(raw)
            self.access_token = parsed.get('access_token', self.access_token)
            self.expires_in = parsed.get('expires_in', self.expires_in)
            self.token_obtained_at = fields.Datetime.now()
        except json.JSONDecodeError:
            pass

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Token Refreshed',
                'message': 'Access token renewed successfully.',
                'type': 'success',
                'sticky': False,
            },
        }

    def action_refresh_token_if_expired(self):
        """Check if current access token is valid; refresh only if it returns 401."""
        if not self.access_token:
            raise UserError('No access token available. Complete Step 4 first.')
        if not self.refresh_token:
            raise UserError('No refresh token available. Exchange an authorization code first (Step 4).')

        url = 'https://b2b.revolut.com/api/1.0/accounts'
        try:
            req = urllib.request.Request(url)
            req.add_header('Authorization', f'Bearer {self.access_token.strip()}')
            with urllib.request.urlopen(req, timeout=15) as resp:
                resp.read()  # consume body
            # 200 — token still valid
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Token Valid',
                    'message': 'Access token is still active — no refresh needed.',
                    'type': 'info',
                    'sticky': False,
                },
            }
        except urllib.error.HTTPError as e:
            if e.code == 401:
                self.action_refresh_token()
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Token Refreshed',
                        'message': 'Access token was expired and has been renewed successfully.',
                        'type': 'success',
                        'sticky': False,
                    },
                }
            raise UserError(f'Revolut API returned HTTP {e.code}: {e.read().decode()}')
        except Exception as e:
            raise UserError(f'Request failed: {e}')

    def action_test_api(self):
        """GET Revolut accounts endpoint with Bearer token."""
        if not self.access_token:
            raise UserError('No access token available. Complete Step 4 first.')

        url = 'https://b2b.revolut.com/api/1.0/accounts'
        try:
            req = urllib.request.Request(url)
            req.add_header('Authorization', f'Bearer {self.access_token}')
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode()
        except urllib.error.HTTPError as e:
            raw = e.read().decode()
        except Exception as e:
            raise UserError(f'Request failed: {e}')

        self.api_test_result = raw

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'API Test Complete',
                'message': 'Response received and stored below.',
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    def _do_refresh_token(self):
        """
        Programmatically refresh the Revolut access token using the stored
        refresh_token + client_assertion.  Updates the DB record and returns
        the new access_token string, or None if refresh is impossible/fails.
        Designed to be called silently from API helpers on a 401 response.
        """
        self.ensure_one()
        if not self.refresh_token or not self.client_assertion or not self.jwt_sub:
            _logger.warning(
                "Cannot auto-refresh Revolut token: missing refresh_token, "
                "client_assertion, or jwt_sub."
            )
            return None

        url = 'https://b2b.revolut.com/api/1.0/auth/token'
        data = urllib.parse.urlencode({
            'grant_type': 'refresh_token',
            'refresh_token': self.refresh_token,
            'client_assertion_type': 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer',
            'client_assertion': self.client_assertion,
            'client_id': self.jwt_sub,
        }).encode()

        try:
            req = urllib.request.Request(url, data=data, method='POST')
            req.add_header('Content-Type', 'application/x-www-form-urlencoded')
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode()
            parsed = json.loads(raw)
        except Exception as e:
            _logger.warning("Revolut token auto-refresh failed: %s", e)
            return None

        new_token = parsed.get('access_token')
        if not new_token:
            _logger.warning("Revolut token auto-refresh: no access_token in response: %s", raw[:300])
            return None

        vals = {
            'access_token': new_token,
            'expires_in': parsed.get('expires_in', self.expires_in),
            'token_obtained_at': fields.Datetime.now(),
            'token_refresh_result': raw,
        }
        if parsed.get('refresh_token'):
            vals['refresh_token'] = parsed['refresh_token']
        self.write(vals)
        _logger.info("Revolut access token auto-refreshed successfully for company %s.", self.company_id.name)
        return new_token

    def action_fetch_revolut_accounts(self):
        """Fetch Revolut accounts and create/update mapping records."""
        self.ensure_one()
        if not self.access_token:
            raise UserError(
                'No access token found. Complete Step 4 first.'
            )

        token = self.access_token.strip()
        url = 'https://b2b.revolut.com/api/1.0/accounts'
        req = urllib.request.Request(url)
        req.add_header('Accept', 'application/json')
        req.add_header('Authorization', f'Bearer {token}')
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                accounts = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 401:
                new_token = self._do_refresh_token()
                if new_token:
                    req = urllib.request.Request(url)
                    req.add_header('Accept', 'application/json')
                    req.add_header('Authorization', f'Bearer {new_token}')
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        accounts = json.loads(resp.read().decode())
                else:
                    raise UserError('Token expired and auto-refresh failed.')
            else:
                raise UserError(f'Revolut API error {e.code}: {e.read().decode()}')
        except Exception as e:
            raise UserError(f'Request failed: {e}')

        if not isinstance(accounts, list):
            raise UserError(f'Unexpected response from /accounts: {type(accounts).__name__}')

        Map = self.env['revolut.account.journal.map']
        created = 0
        updated = 0

        for acct in accounts:
            acct_id = acct.get('id')
            if not acct_id:
                continue

            acct_name = acct.get('name') or acct_id
            acct_currency = acct.get('currency')
            acct_balance = acct.get('balance', 0.0)

            currency = self.env['res.currency'].search(
                [('name', '=', acct_currency)], limit=1
            ) if acct_currency else False

            # Extract bank details from first element if present
            bank_details = {}
            bd_list = acct.get('bank_details')
            if bd_list and isinstance(bd_list, list) and len(bd_list) > 0:
                bank_details = bd_list[0] if isinstance(bd_list[0], dict) else {}

            # Parse Revolut timestamps
            revolut_created = False
            revolut_updated = False
            if acct.get('created_at'):
                try:
                    revolut_created = datetime.datetime.fromisoformat(
                        acct['created_at'].replace('Z', '+00:00')
                    ).strftime('%Y-%m-%d %H:%M:%S')
                except (ValueError, AttributeError):
                    pass
            if acct.get('updated_at'):
                try:
                    revolut_updated = datetime.datetime.fromisoformat(
                        acct['updated_at'].replace('Z', '+00:00')
                    ).strftime('%Y-%m-%d %H:%M:%S')
                except (ValueError, AttributeError):
                    pass

            # Map Revolut state to selection value
            raw_state = (acct.get('state') or '').lower()
            revolut_state = raw_state if raw_state in ('active', 'inactive') else False

            existing = Map.search([
                ('revolut_account_id', '=', acct_id),
                ('company_id', '=', self.company_id.id),
            ], limit=1)

            vals = {
                'revolut_account_name': acct_name,
                'last_sync_balance': acct_balance,
                'config_id': self.id,
                'revolut_account_state': revolut_state,
                'revolut_public': bool(acct.get('public')),
                'revolut_created_at': revolut_created or False,
                'revolut_updated_at': revolut_updated or False,
                'iban': bank_details.get('iban') or False,
                'bic': bank_details.get('bic') or False,
                'sort_code': bank_details.get('sort_code') or False,
                'account_no': bank_details.get('account_no') or False,
                'routing_number': bank_details.get('routing_number') or False,
                'beneficiary': bank_details.get('beneficiary') or False,
                'bank_country': bank_details.get('bank_country') or False,
                'raw_json': json.dumps(acct, indent=2, default=str),
            }
            if currency:
                vals['currency_id'] = currency.id

            if existing:
                existing.write(vals)
                updated += 1
            else:
                vals.update({
                    'revolut_account_id': acct_id,
                    'company_id': self.company_id.id,
                })
                Map.create(vals)
                created += 1

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Revolut Accounts Fetched',
                'message': (
                    f'Found {len(accounts)} account(s): '
                    f'{created} new, {updated} updated. '
                    f'Now link each account to an Odoo bank journal.'
                ),
                'type': 'success',
                'sticky': True,
            },
        }

    @api.model
    def action_open_config(self):
        """Get-or-create singleton record for current company; return form action."""
        if not self.env.user.has_group('legacy_accounting_helper.group_revolut_admin'):
            raise UserError(
                "You need Revolut Business API Integration / Administrator access "
                "to open this configuration page."
            )
        record = self.sudo().search([('company_id', '=', self.env.company.id)], limit=1)
        if not record:
            record = self.sudo().create({'company_id': self.env.company.id})

        return {
            'type': 'ir.actions.act_window',
            'name': 'Revolut Business API Configuration',
            'res_model': 'legacy.accounting.config',
            'res_id': record.id,
            'view_mode': 'form',
            'view_type': 'form',
            'target': 'current',
        }

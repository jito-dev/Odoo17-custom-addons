import base64
import datetime
import json
import os
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request

from odoo import api, fields, models
from odoo.exceptions import UserError


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

    @api.model
    def action_open_config(self):
        """Get-or-create singleton record for current company; return form action."""
        record = self.search([('company_id', '=', self.env.company.id)], limit=1)
        if not record:
            record = self.create({'company_id': self.env.company.id})

        return {
            'type': 'ir.actions.act_window',
            'name': 'Revolut Business API Configuration',
            'res_model': 'legacy.accounting.config',
            'res_id': record.id,
            'view_mode': 'form',
            'view_type': 'form',
            'target': 'current',
        }

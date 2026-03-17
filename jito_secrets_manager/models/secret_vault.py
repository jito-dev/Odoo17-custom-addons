import os
import base64
import hashlib
import logging
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# ── In-memory vault key — cleared on every Odoo restart (= auto-sealed) ──────
_VAULT_KEY: Optional[bytes] = None

_SALT_PARAM = 'jito_secrets_manager.vault_salt'
_VERIFIER_PARAM = 'jito_secrets_manager.vault_verifier'
_ITERATIONS = 480_000


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    """Derive a Fernet-compatible key from a passphrase using PBKDF2-SHA256."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=_ITERATIONS,
    )
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode('utf-8')))


def _make_verifier(passphrase: str, salt: bytes) -> str:
    """Create a stored verifier so we can validate the passphrase on unseal."""
    # Separate derivation with a different purpose suffix to avoid key reuse
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt + b'_verify',
        iterations=_ITERATIONS,
    )
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode('utf-8'))).decode()


class SecretVault(models.Model):
    """
    Singleton model that manages the vault seal/unseal state.

    The actual encryption key is held ONLY in the module-level _VAULT_KEY variable.
    It is never persisted — Odoo restart automatically seals the vault.
    """
    _name = 'secret.vault'
    _description = 'Secrets Vault'

    name = fields.Char(default='Vault', readonly=True)
    is_initialized = fields.Boolean(
        string='Vault Initialized',
        compute='_compute_status',
    )
    is_unsealed = fields.Boolean(
        string='Unsealed',
        compute='_compute_status',
    )
    state = fields.Char(
        string='State',
        compute='_compute_status',
    )

    @api.depends()
    def _compute_status(self):
        global _VAULT_KEY
        salt = self.env['ir.config_parameter'].sudo().get_param(_SALT_PARAM)
        for rec in self:
            rec.is_initialized = bool(salt)
            rec.is_unsealed = _VAULT_KEY is not None
            rec.state = 'unsealed' if _VAULT_KEY is not None else 'sealed'

    # ── Singleton helpers ─────────────────────────────────────────────────────

    @api.model
    def _get_vault(self):
        vault = self.search([], limit=1)
        if not vault:
            vault = self.create({'name': 'Vault'})
        return vault

    # ── Seal / Unseal ─────────────────────────────────────────────────────────

    @api.model
    def unseal(self, passphrase: str):
        """Derive the key from passphrase and hold it in memory."""
        global _VAULT_KEY

        ICP = self.env['ir.config_parameter'].sudo()
        salt_b64 = ICP.get_param(_SALT_PARAM)
        verifier = ICP.get_param(_VERIFIER_PARAM)

        if not salt_b64 or not verifier:
            raise UserError(_(
                'Vault has not been initialized yet. '
                'Please set an initial passphrase first.'
            ))

        salt = base64.urlsafe_b64decode(salt_b64.encode())
        expected_verifier = _make_verifier(passphrase, salt)

        if expected_verifier != verifier:
            raise UserError(_('Incorrect passphrase. The vault remains sealed.'))

        _VAULT_KEY = _derive_key(passphrase, salt)
        _logger.info('Secrets vault unsealed by user %s (id=%s)', self.env.user.name, self.env.uid)

        self.env['secret.audit.log'].sudo()._log(
            secret=None,
            action='unseal',
        )

    @api.model
    def initialize(self, passphrase: str):
        """First-time setup: generate salt, derive key, store verifier."""
        global _VAULT_KEY

        ICP = self.env['ir.config_parameter'].sudo()
        if ICP.get_param(_SALT_PARAM):
            raise UserError(_('Vault is already initialized. Use unseal instead.'))

        salt = os.urandom(32)
        salt_b64 = base64.urlsafe_b64encode(salt).decode()
        verifier = _make_verifier(passphrase, salt)

        ICP.set_param(_SALT_PARAM, salt_b64)
        ICP.set_param(_VERIFIER_PARAM, verifier)

        _VAULT_KEY = _derive_key(passphrase, salt)
        _logger.info('Secrets vault initialized by user %s', self.env.user.name)

        self.env['secret.audit.log'].sudo()._log(
            secret=None,
            action='unseal',
        )

    @api.model
    def seal(self):
        """Clear the in-memory key — vault becomes sealed."""
        global _VAULT_KEY
        _VAULT_KEY = None
        _logger.info('Secrets vault sealed by user %s (id=%s)', self.env.user.name, self.env.uid)

        self.env['secret.audit.log'].sudo()._log(
            secret=None,
            action='seal',
        )

    # ── Encryption service ────────────────────────────────────────────────────

    @api.model
    def encrypt(self, plaintext: str) -> str:
        """Encrypt a string. Raises UserError if vault is sealed."""
        if _VAULT_KEY is None:
            raise UserError(_(
                'The vault is sealed. Please unseal it before saving secrets.'
            ))
        f = Fernet(_VAULT_KEY)
        return f.encrypt(plaintext.encode('utf-8')).decode('ascii')

    @api.model
    def decrypt(self, ciphertext: str) -> str:
        """Decrypt a string. Raises UserError if vault is sealed or token invalid."""
        if _VAULT_KEY is None:
            raise UserError(_(
                'The vault is sealed. Please unseal it to view secrets.'
            ))
        try:
            f = Fernet(_VAULT_KEY)
            return f.decrypt(ciphertext.encode('ascii')).decode('utf-8')
        except InvalidToken:
            raise UserError(_(
                'Failed to decrypt secret. The vault key may have changed.'
            ))

    @api.model
    def get_state(self) -> dict:
        """Return vault state as dict for client-side use."""
        global _VAULT_KEY
        ICP = self.env['ir.config_parameter'].sudo()
        return {
            'is_initialized': bool(ICP.get_param(_SALT_PARAM)),
            'is_unsealed': _VAULT_KEY is not None,
        }

    @api.model
    def action_open_vault_singleton(self):
        """Menu action — ensures the singleton exists and opens its form."""
        vault = self._get_vault()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Vault'),
            'res_model': 'secret.vault',
            'view_mode': 'form',
            'res_id': vault.id,
            'target': 'current',
            'views': [(False, 'form')],
        }

    def action_open_unseal_wizard(self):
        """Open the unseal/initialize wizard."""
        ICP = self.env['ir.config_parameter'].sudo()
        is_initialized = bool(ICP.get_param(_SALT_PARAM))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Initialize Vault') if not is_initialized else _('Unseal Vault'),
            'res_model': 'secret.unseal.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_is_initialized': is_initialized},
        }

    def action_seal(self):
        """Seal the vault from the UI."""
        self.seal()
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

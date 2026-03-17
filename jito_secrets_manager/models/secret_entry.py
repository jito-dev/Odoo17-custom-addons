import json
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

SECRET_TYPES = [
    ('login',   'Login + Password'),
    ('card',    'Credit / Debit Card'),
    ('generic', 'Generic Data'),
    ('cert',    'Public/Private Cert'),
]

# Default field schemas per type (structure only — values filled by user)
# multiline=True renders as a textarea in the Owl widget.
DEFAULT_FIELDS = {
    'login': [
        {'key': 'login',    'label': 'Login',    'value': '', 'sensitive': False, 'multiline': False},
        {'key': 'password', 'label': 'Password', 'value': '', 'sensitive': True,  'multiline': False},
    ],
    'card': [
        {'key': 'card_number',     'label': 'Card Number',     'value': '', 'sensitive': True,  'multiline': False},
        {'key': 'cvv',             'label': 'CVV',             'value': '', 'sensitive': True,  'multiline': False},
        {'key': 'expiration_date', 'label': 'Expiration Date', 'value': '', 'sensitive': False, 'multiline': False},
    ],
    'generic': [
        {'key': 'data', 'label': 'Data', 'value': '', 'sensitive': True, 'multiline': False},
    ],
    'cert': [
        {'key': 'public_cert',  'label': 'Public Certification', 'value': '', 'sensitive': False, 'multiline': True},
        {'key': 'private_cert', 'label': 'Private Certificate',  'value': '', 'sensitive': True,  'multiline': True},
    ],
}


class SecretEntry(models.Model):
    _name = 'secret.entry'
    _description = 'Secret Entry'
    _order = 'name'

    name = fields.Char(
        string='Name',
        required=True,
        help='A descriptive title for this secret (not encrypted).',
    )
    secret_type = fields.Selection(
        selection=SECRET_TYPES,
        string='Type',
        required=True,
        default='login',
    )
    encrypted_payload = fields.Text(
        string='Encrypted Payload',
        readonly=True,
        copy=False,
        help='Fernet-encrypted JSON containing all secret field values.',
    )
    tag_ids = fields.Many2many(
        'secret.tag',
        'secret_entry_tag_rel',
        'entry_id',
        'tag_id',
        string='Tags',
    )
    user_id = fields.Many2one(
        'res.users',
        string='Owner',
        required=True,
        default=lambda self: self.env.uid,
        index=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
    )
    share_ids = fields.One2many(
        'secret.share',
        'secret_id',
        string='Shares',
    )
    audit_log_ids = fields.One2many(
        'secret.audit.log',
        'secret_id',
        string='Audit Log',
    )
    share_count = fields.Integer(
        string='Shares',
        compute='_compute_share_count',
    )
    is_shared_with_me = fields.Boolean(
        string='Shared with Me',
        compute='_compute_is_shared_with_me',
    )
    vault_is_unsealed = fields.Boolean(
        string='Vault Unsealed',
        compute='_compute_vault_state',
    )
    # Staging field — carries plaintext JSON payload from the widget to the model.
    # Our create()/write() overrides encrypt it into encrypted_payload and pop it
    # from vals before super(), so the column always stays NULL in the database.
    transient_payload = fields.Text(
        string='Payload (transient)',
        copy=False,
    )

    @api.depends('share_ids')
    def _compute_share_count(self):
        for rec in self:
            rec.share_count = len(rec.share_ids)

    @api.depends('share_ids', 'share_ids.shared_with_user_id', 'share_ids.expires_at')
    def _compute_is_shared_with_me(self):
        now = fields.Datetime.now()
        for rec in self:
            rec.is_shared_with_me = any(
                s.shared_with_user_id.id == self.env.uid and
                (not s.expires_at or s.expires_at > now)
                for s in rec.share_ids
            )

    @api.depends()
    def _compute_vault_state(self):
        from . import secret_vault as sv
        is_open = sv._VAULT_KEY is not None
        for rec in self:
            rec.vault_is_unsealed = is_open

    # ── Payload helpers ───────────────────────────────────────────────────────

    def _get_payload(self) -> dict:
        """Decrypt and return the payload dict. Raises if sealed or no payload."""
        self.ensure_one()
        if not self.encrypted_payload:
            secret_type = self.secret_type or 'login'
            return {
                'type': secret_type,
                'fields': [dict(f) for f in DEFAULT_FIELDS.get(secret_type, [])],
                'custom_fields': [],
            }
        plaintext = self.env['secret.vault'].decrypt(self.encrypted_payload)
        return json.loads(plaintext)

    def _set_payload(self, data: dict):
        """Encrypt and store the payload dict."""
        self.ensure_one()
        plaintext = json.dumps(data, ensure_ascii=False)
        self.encrypted_payload = self.env['secret.vault'].encrypt(plaintext)

    # ── ORM overrides: encrypt transient_payload + audit ─────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('transient_payload'):
                vals['encrypted_payload'] = self.env['secret.vault'].encrypt(
                    vals.pop('transient_payload')
                )
            else:
                vals.pop('transient_payload', None)
        records = super().create(vals_list)
        for rec in records:
            self.env['secret.audit.log'].sudo()._log(rec, 'create')
        return records

    def write(self, vals):
        if vals.get('transient_payload'):
            vals['encrypted_payload'] = self.env['secret.vault'].encrypt(
                vals.pop('transient_payload')
            )
        else:
            vals.pop('transient_payload', None)
        result = super().write(vals)
        if 'encrypted_payload' in vals or 'name' in vals:
            for rec in self:
                self.env['secret.audit.log'].sudo()._log(rec, 'edit')
        return result

    def unlink(self):
        for rec in self:
            self.env['secret.audit.log'].sudo()._log(rec, 'delete')
        return super().unlink()

    # ── RPC methods called by the Owl widget ──────────────────────────────────

    def get_decrypted_payload(self):
        """Return the full decrypted payload for the widget. Logs reveal."""
        self.ensure_one()
        payload = self._get_payload()
        self.env['secret.audit.log'].sudo()._log(self, 'reveal')
        return payload

    def save_payload(self, payload: dict):
        """Save an updated payload dict from the widget (used on existing records)."""
        self.ensure_one()
        self._set_payload(payload)
        self.env['secret.audit.log'].sudo()._log(self, 'edit')
        return True

    @api.onchange('secret_type')
    def _onchange_secret_type(self):
        """Reset transient_payload to the default schema whenever the type changes.
        The Owl widget reads this value in onWillUpdateProps to detect the change."""
        if not self.secret_type:
            return
        default_fields = DEFAULT_FIELDS.get(self.secret_type, [])
        payload = {
            'type': self.secret_type,
            'fields': [dict(f) for f in default_fields],
            'custom_fields': [],
        }
        self.transient_payload = json.dumps(payload)

    @api.model
    def get_default_fields(self, secret_type: str) -> list:
        """Return the default field schema for a given secret type."""
        return [dict(f) for f in DEFAULT_FIELDS.get(secret_type, [])]

    @api.model
    def get_vault_state(self) -> dict:
        """Return current vault state (for widget bootstrap)."""
        return self.env['secret.vault'].get_state()

    @api.model
    def action_open_new_form(self):
        """Open a blank create form. Called from the list view header button."""
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'secret.entry',
            'views': [[False, 'form']],
            'target': 'current',
            'context': {'default_user_id': self.env.uid},
        }

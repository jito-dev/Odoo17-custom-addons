from odoo import api, fields, models, _
from odoo.exceptions import UserError


class UnsealWizard(models.TransientModel):
    _name = 'secret.unseal.wizard'
    _description = 'Vault Unseal Wizard'

    is_initialized = fields.Boolean(
        string='Vault Initialized',
        default=lambda self: self._default_is_initialized(),
    )
    passphrase = fields.Char(
        string='Master Passphrase',
        required=True,
    )
    passphrase_confirm = fields.Char(
        string='Confirm Passphrase',
        help='Required only when initializing the vault for the first time.',
    )

    def _default_is_initialized(self):
        ICP = self.env['ir.config_parameter'].sudo()
        return bool(ICP.get_param('jito_secrets_manager.vault_salt'))

    def action_confirm(self):
        """Initialize or unseal the vault depending on state."""
        vault = self.env['secret.vault']

        if not self.is_initialized:
            # First-time initialization
            if self.passphrase != self.passphrase_confirm:
                raise UserError(_('Passphrases do not match. Please try again.'))
            if len(self.passphrase) < 12:
                raise UserError(_('Passphrase must be at least 12 characters long.'))
            vault.initialize(self.passphrase)
        else:
            vault.unseal(self.passphrase)

        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

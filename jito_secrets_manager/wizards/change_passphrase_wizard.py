from odoo import fields, models, _
from odoo.exceptions import UserError


class ChangePassphraseWizard(models.TransientModel):
    _name = 'secret.change.passphrase.wizard'
    _description = 'Change Vault Passphrase'

    current_passphrase = fields.Char(string='Current Passphrase', required=True)
    new_passphrase = fields.Char(string='New Passphrase', required=True)
    new_passphrase_confirm = fields.Char(string='Confirm New Passphrase', required=True)

    def action_confirm(self):
        self.ensure_one()
        if self.new_passphrase != self.new_passphrase_confirm:
            raise UserError(_('New passphrase and confirmation do not match.'))
        self.env['secret.vault'].rekey(
            self.current_passphrase,
            self.new_passphrase,
        )
        return {'type': 'ir.actions.client', 'tag': 'reload'}

from odoo import api, fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    custom_invoice_ref = fields.Char(
        string='Custom Invoice Reference',
        copy=False,
        tracking=True,
        help='External system invoice reference. Format: INV-YYYY-N',
    )
    custom_invoice_ref_locked = fields.Boolean(
        string='Custom Ref Locked',
        default=False,
        copy=False,
    )

    def action_lock_custom_invoice_ref(self):
        self.ensure_one()
        self.custom_invoice_ref_locked = True

    def action_unlock_custom_invoice_ref(self):
        self.ensure_one()
        self.custom_invoice_ref_locked = False

    @api.onchange('custom_invoice_ref')
    def _onchange_custom_invoice_ref_duplicate(self):
        if not self.custom_invoice_ref:
            return
        domain = [
            ('custom_invoice_ref', '=', self.custom_invoice_ref),
            ('move_type', '=', 'out_invoice'),
        ]
        if self.id:
            domain.append(('id', '!=', self.id))
        duplicate = self.env['account.move'].search(domain, limit=1)
        if duplicate:
            return {
                'warning': {
                    'title': 'Duplicate Custom Invoice Reference',
                    'message': (
                        f'The reference "{self.custom_invoice_ref}" is already used '
                        f'on invoice {duplicate.name}.'
                    ),
                }
            }

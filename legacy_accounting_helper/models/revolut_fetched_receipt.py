import logging

from odoo import fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class RevolutFetchedReceipt(models.Model):
    """Staged receipt downloaded from Revolut, pending explicit user attachment."""
    _name = 'revolut.fetched.receipt'
    _description = 'Staged Revolut Receipt'
    _order = 'id'

    transaction_id = fields.Many2one(
        'revolut.transaction',
        string='Transaction',
        ondelete='cascade',
        required=True,
        index=True,
    )
    attachment_id = fields.Many2one(
        'ir.attachment',
        string='File',
        ondelete='restrict',
    )
    revolut_expense_id = fields.Char(string='Expense ID')
    revolut_receipt_id = fields.Char(string='Receipt ID')
    name = fields.Char(string='Filename')
    mime_type = fields.Char(string='Type')
    is_attached = fields.Boolean(string='Attached', default=False)

    def action_preview(self):
        """Open the receipt file in a new browser tab for preview."""
        self.ensure_one()
        if not self.attachment_id:
            raise UserError(_("No file available for preview."))
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{self.attachment_id.id}?download=false',
            'target': 'new',
        }

    def action_attach(self):
        """Link this receipt to the transaction's invoice_attachment_ids."""
        self.ensure_one()
        if not self.attachment_id:
            raise UserError(_("No file to attach."))
        self.transaction_id.write({
            'invoice_attachment_ids': [(4, self.attachment_id.id)],
        })
        self.is_attached = True
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Attached'),
                'message': _('"%s" has been attached to the transaction.', self.name),
                'type': 'success',
                'sticky': False,
            },
        }

    def unlink(self):
        """Delete orphaned ir.attachments when staged receipts are removed."""
        # Only delete attachments that have not been linked to the transaction yet
        attachments_to_delete = (
            self.filtered(lambda r: not r.is_attached).mapped('attachment_id')
        )
        result = super().unlink()
        attachments_to_delete.sudo().unlink()
        return result

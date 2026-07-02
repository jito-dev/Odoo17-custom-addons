from odoo import models


class IrAttachment(models.Model):
    _inherit = 'ir.attachment'

    def register_as_main_attachment(self, force=True):
        """Trigger AI extraction when a PDF is attached to a vendor bill."""
        super().register_as_main_attachment(force=force)

        if self.res_model == 'account.move' and self.res_id:
            move = self.env['account.move'].browse(self.res_id)
            if (
                move.exists()
                and move.is_purchase_document()
                and move.state == 'draft'
                and move.ai_extract_state == 'no_extract'
                and move.company_id.ai_invoice_extract_mode == 'auto_send'
            ):
                move._ai_extract_invoice_data()

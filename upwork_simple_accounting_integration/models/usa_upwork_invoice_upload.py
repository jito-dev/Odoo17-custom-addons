import base64
import logging
import re

from odoo import fields, models, _

_logger = logging.getLogger(__name__)


class UsaUpworkInvoiceUpload(models.TransientModel):
    """Wizard: bulk-upload Upwork PDF invoices and auto-match to transactions by Record ID."""

    _name = 'usa.upwork.invoice.upload'
    _description = 'Upload Upwork Invoices'

    attachment_ids = fields.Many2many(
        'ir.attachment',
        'usa_upwork_invoice_upload_att_rel',
        'wizard_id',
        'attachment_id',
        string='Invoice PDFs',
    )

    def action_upload(self):
        """Match each uploaded PDF to a transaction by Record ID extracted from filename.

        Filename pattern: ..._T<record_id>_invoice.pdf  → record_id = digits after T.
        Writes binary data + filename to the matched usa.transaction record.
        Returns a notification action summarising matched / unmatched counts.
        """
        self.ensure_one()

        matched = []
        unmatched = []

        for att in self.attachment_ids:
            filename = att.name or ''
            m = re.search(r'T(\d+)', filename)
            if not m:
                unmatched.append(filename)
                _logger.warning('Upwork invoice upload: no Record ID found in "%s"', filename)
                continue

            record_id = m.group(1)
            transaction = self.env['usa.transaction'].search(
                [('record_id', '=', record_id)], limit=1)

            if not transaction:
                unmatched.append(filename)
                _logger.warning(
                    'Upwork invoice upload: no transaction found for Record ID %s (file: %s)',
                    record_id, filename)
                continue

            # Read raw binary from the ir.attachment (bypass bin_size context)
            pdf_data = att.with_context(bin_size=False).datas
            transaction.write({
                'upwork_invoice_pdf': pdf_data,
                'upwork_invoice_filename': filename,
            })
            matched.append(filename)
            _logger.info(
                'Upwork invoice upload: matched "%s" → transaction %s (id=%s)',
                filename, record_id, transaction.id)

        summary = _('Matched: %(matched)d, Unmatched: %(unmatched)d',
                    matched=len(matched), unmatched=len(unmatched))
        if unmatched:
            detail = _('\n\nUnmatched files:\n') + '\n'.join(unmatched)
            summary += detail

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Upload Complete'),
                'message': summary,
                'type': 'success' if not unmatched else 'warning',
                'sticky': bool(unmatched),
            },
        }

    def action_open_wizard(self):
        """Open this wizard in a dialog window (used by server action)."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Upload Upwork Invoices'),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

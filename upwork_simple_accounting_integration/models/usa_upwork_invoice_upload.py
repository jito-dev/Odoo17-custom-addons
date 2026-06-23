import base64
import logging
import re

from odoo import fields, models, _

_logger = logging.getLogger(__name__)


class UsaUpworkInvoiceUpload(models.TransientModel):
    """Wizard: bulk-upload Upwork PDF invoices and auto-match to transactions.

    Matching strategy (tried in order for each file):
    1. Extract digits from the first ``T<digits>`` token in the filename.
    2. Search by ``record_id`` — covers the long filename pattern
       ``2026-03-15_..._T899387936_invoice.pdf``.
    3. If not found, search by ``related_invoice_id`` — covers the short
       filename pattern ``T895737930.pdf``.
    """

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
        """Match each uploaded PDF to a transaction and attach it.

        Returns a notification action summarising matched / unmatched counts.
        """
        self.ensure_one()

        matched = []
        unmatched = []

        Transaction = self.env['usa.transaction']

        for att in self.attachment_ids:
            filename = att.name or ''
            m = re.search(r'T(\d+)', filename)
            if not m:
                unmatched.append(filename)
                _logger.warning('Upwork invoice upload: no T<id> token found in "%s"', filename)
                continue

            invoice_number = m.group(1)

            # ── Match attempt 1: by record_id ─────────────────────────────
            transaction = Transaction.search([('record_id', '=', invoice_number)], limit=1)

            # ── Match attempt 2: by related_invoice_id ────────────────────
            if not transaction:
                transaction = Transaction.search(
                    [('related_invoice_id', '=', invoice_number)], limit=1)
                if transaction:
                    _logger.info(
                        'Upwork invoice upload: matched "%s" via related_invoice_id %s → tx id=%s',
                        filename, invoice_number, transaction.id)

            if not transaction:
                unmatched.append(filename)
                _logger.warning(
                    'Upwork invoice upload: no transaction found for T%s (file: %s)',
                    invoice_number, filename)
                continue

            # Read raw binary from the ir.attachment (bypass bin_size context)
            pdf_data = att.with_context(bin_size=False).datas
            transaction.write({
                'upwork_invoice_pdf': pdf_data,
                'upwork_invoice_filename': filename,
            })
            matched.append(filename)
            _logger.info(
                'Upwork invoice upload: matched "%s" → transaction record_id=%s (id=%s)',
                filename, transaction.record_id, transaction.id)

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

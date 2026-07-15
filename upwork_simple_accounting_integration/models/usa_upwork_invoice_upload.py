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
        """Split each uploaded Upwork PDF into single pages and route them to the
        right transactions (delegates to usa.transaction._ingest_upwork_document)."""
        self.ensure_one()
        Tx = self.env['usa.transaction']
        results = [
            Tx._ingest_upwork_document(
                att.name or '',
                base64.b64decode(att.with_context(bin_size=False).datas or b''))
            for att in self.attachment_ids
        ]
        _PARTIAL = ('fee_tx_missing', 'payment_tx_missing')
        routed = [r for r in results if r['status'] == 'routed']
        partial = [r for r in results if r['status'] in _PARTIAL]
        failed = [r for r in results if r['status'] not in (('routed',) + _PARTIAL)]
        pages = sum(len(r['routed']) for r in results)
        n_cust = sum(1 for r in results for x in r['routed'] if x['role'].startswith('customer'))
        n_vend = sum(1 for r in results for x in r['routed'] if x['role'].startswith('vendor'))
        n_transfer = sum(1 for r in results for x in r['routed'] if x['role'] == 'withdrawal_summary')
        n_card = sum(1 for r in results for x in r['routed'] if x['role'] in ('card_invoice', 'card_receipt'))

        lines = [
            _('%(r)d routed, %(p)d partial, %(f)d failed.',
              r=len(routed), p=len(partial), f=len(failed)),
            _('Pages stored: %(pages)d (%(cust)d customer docs, %(vend)d vendor docs, '
              '%(tr)d transfer summaries, %(card)d card-payment docs).',
              pages=pages, cust=n_cust, vend=n_vend, tr=n_transfer, card=n_card),
        ]
        if failed or partial:
            lines.append('')
            lines += ['• %s — %s' % (r['filename'], r['message']) for r in (failed + partial)]

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Upload Complete'),
                'message': '\n'.join(lines),
                'type': 'success' if not (failed or partial) else 'warning',
                'sticky': bool(failed or partial),
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

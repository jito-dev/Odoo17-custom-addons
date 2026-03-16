import base64
import json
import logging
import re

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class UpworkInvoiceUploadController(http.Controller):
    """HTTP endpoint for Upwork invoice PDF uploads.

    Accepts one file per request so each POST body is small and cannot
    exceed the nginx client_max_body_size limit — the root cause of the
    JSON parse error when using many2many_binary for bulk uploads.
    """

    @http.route(
        '/upwork/invoice_upload',
        type='http',
        auth='user',
        methods=['POST'],
        csrf=True,
    )
    def invoice_upload(self, ufile=None, **kwargs):
        """Match a single PDF to a usa.transaction and attach it.

        Returns JSON:
            {matched: true,  filename: str, record_id: str}
            {matched: false, filename: str, reason: str}
            {error: str}
        """
        if not ufile:
            return self._json({'error': 'No file provided'})

        filename = ufile.filename or ''
        try:
            pdf_b64 = base64.b64encode(ufile.read()).decode()
        except Exception as exc:
            _logger.error('invoice_upload: could not read "%s": %s', filename, exc)
            return self._json({'error': str(exc)})

        m = re.search(r'T(\d+)', filename)
        if not m:
            return self._json({'matched': False, 'filename': filename, 'reason': 'no_id'})

        invoice_number = m.group(1)
        Transaction = request.env['usa.transaction']

        tx = Transaction.search([('record_id', '=', invoice_number)], limit=1)
        if not tx:
            tx = Transaction.search(
                [('related_invoice_id', '=', invoice_number)], limit=1)

        if not tx:
            _logger.warning(
                'invoice_upload: no transaction for T%s (file: %s)', invoice_number, filename)
            return self._json({
                'matched': False, 'filename': filename, 'reason': 'no_transaction'})

        tx.write({
            'upwork_invoice_pdf': pdf_b64,
            'upwork_invoice_filename': filename,
        })
        _logger.info(
            'invoice_upload: matched "%s" → record_id=%s (tx id=%s)',
            filename, tx.record_id, tx.id)
        return self._json({'matched': True, 'filename': filename, 'record_id': invoice_number})

    @staticmethod
    def _json(data):
        return request.make_response(
            json.dumps(data),
            headers=[('Content-Type', 'application/json')],
        )

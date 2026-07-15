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
            raw = ufile.read()
        except Exception as exc:
            _logger.error('invoice_upload: could not read "%s": %s', filename, exc)
            return self._json({'error': str(exc)})

        # Split the multi-page Upwork PDF and route its pages to the right
        # transactions (shared logic — see models/usa_pdf_ingest.py).
        result = request.env['usa.transaction'].sudo()._ingest_upwork_document(filename, raw)
        # Backward-compat flag for older clients
        result['matched'] = result.get('status') == 'routed'
        return self._json(result)

    @staticmethod
    def _json(data):
        return request.make_response(
            json.dumps(data),
            headers=[('Content-Type', 'application/json')],
        )

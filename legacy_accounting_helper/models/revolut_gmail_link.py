import base64
import logging
from urllib.parse import urlparse, unquote
from os.path import basename

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class RevolutGmailLink(models.Model):
    _name = 'revolut.gmail.link'
    _description = 'Extracted link from Gmail message'
    _order = 'score desc, id'

    message_id = fields.Many2one(
        'revolut.gmail.message',
        string='Email Message',
        ondelete='cascade',
        required=True,
        index=True,
    )
    transaction_id = fields.Many2one(
        related='message_id.transaction_id',
        store=True,
        index=True,
    )
    url = fields.Char(string='URL', required=True)
    link_text = fields.Char(string='Link Text')
    score = fields.Integer(string='Score', default=0)
    match_reasons = fields.Char(string='Match Reasons')
    relevance = fields.Char(
        string='Relevance',
        compute='_compute_relevance',
        store=True,
    )
    is_attached = fields.Boolean(string='Attached', default=False)

    @api.depends('score')
    def _compute_relevance(self):
        for rec in self:
            s = rec.score
            if s >= 8:
                rec.relevance = 'High'
            elif s >= 3:
                rec.relevance = 'Medium'
            elif s >= 0:
                rec.relevance = 'Low'
            else:
                rec.relevance = 'Noise'

    def action_try_attach(self):
        """Download the file from the URL and attach it to the transaction."""
        self.ensure_one()
        import requests

        txn = self.transaction_id
        if not txn:
            raise UserError(_("No linked transaction found."))

        try:
            resp = requests.get(
                self.url,
                timeout=30,
                allow_redirects=True,
                stream=True,
                headers={
                    'User-Agent': (
                        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
                        '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                    ),
                },
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise UserError(_("Failed to download: %s", str(exc)))

        # Read body (cap at 50 MB)
        max_size = 50 * 1024 * 1024
        content = resp.content
        if len(content) > max_size:
            raise UserError(_("File too large (> 50 MB)."))

        # Determine filename
        filename = self._guess_filename(resp, self.url)

        # Determine MIME type
        mimetype = (resp.headers.get('Content-Type') or 'application/octet-stream')
        mimetype = mimetype.split(';')[0].strip()

        # Reject HTML pages — likely not a downloadable file
        if mimetype.startswith('text/html'):
            raise UserError(_(
                "The URL returned an HTML page, not a downloadable file.\n"
                "You may need to open the link in a browser and download manually."
            ))

        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': base64.b64encode(content),
            'mimetype': mimetype,
        })

        txn.write({
            'invoice_attachment_ids': [(4, attachment.id)],
        })
        self.is_attached = True

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Attached'),
                'message': _(
                    '"%s" (%s) has been attached to the transaction.',
                    filename, self._format_size(len(content)),
                ),
                'type': 'success',
                'sticky': False,
            },
        }

    @staticmethod
    def _guess_filename(response, url):
        """Derive a filename from Content-Disposition, URL path, or fallback."""
        # Try Content-Disposition
        cd = response.headers.get('Content-Disposition', '')
        if 'filename' in cd:
            import re
            # filename*=UTF-8''name or filename="name"
            match = re.search(r"filename\*=(?:UTF-8''|utf-8'')(.+?)(?:;|$)", cd, re.I)
            if match:
                return unquote(match.group(1).strip().strip('"'))
            match = re.search(r'filename=(["\']?)(.+?)\1(?:;|$)', cd)
            if match:
                return match.group(2).strip()

        # Try URL path
        parsed = urlparse(url)
        path_name = basename(unquote(parsed.path))
        if path_name and '.' in path_name:
            return path_name

        # Fallback based on Content-Type
        mimetype = (response.headers.get('Content-Type') or '')
        mimetype = mimetype.split(';')[0].strip()
        ext_map = {
            'application/pdf': '.pdf',
            'image/png': '.png',
            'image/jpeg': '.jpg',
            'application/zip': '.zip',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': '.xlsx',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx',
        }
        ext = ext_map.get(mimetype, '')
        return f'downloaded_file{ext}'

    @staticmethod
    def _format_size(size_bytes):
        if size_bytes < 1024:
            return f'{size_bytes} B'
        if size_bytes < 1024 * 1024:
            return f'{size_bytes // 1024} KB'
        return f'{size_bytes / (1024 * 1024):.1f} MB'

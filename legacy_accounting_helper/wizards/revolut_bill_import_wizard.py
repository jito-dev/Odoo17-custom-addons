import base64
import hashlib
import io
import logging
import zipfile

from odoo import _, fields, models
from odoo.exceptions import UserError
from odoo.tools.mimetypes import guess_mimetype

_logger = logging.getLogger(__name__)


class RevolutBillImportWizard(models.TransientModel):
    _name = 'revolut.bill.import.wizard'
    _description = 'Import Revolut bill/receipt documents from an exported .zip'

    zip_file = fields.Binary(string='Bills .zip', required=True)
    zip_filename = fields.Char(string='Filename')

    def action_import(self):
        """Re-attach each file in the uploaded .zip to the transaction whose
        ``revolut_id`` matches the filename prefix. Files are named
        ``<revolut_id>.<attachment_id>.<ext>`` (as produced by Export Bills);
        the ``<attachment_id>`` segment only disambiguates multiple receipts
        on a tx and is not used for matching. Content-deduped (SHA1), so
        re-importing the same zip is a no-op. Never creates bills."""
        self.ensure_one()
        if not self.zip_file:
            raise UserError(_('Please upload a .zip exported with "Export Bills".'))

        try:
            archive = zipfile.ZipFile(io.BytesIO(base64.b64decode(self.zip_file)))
        except zipfile.BadZipFile:
            raise UserError(_('The uploaded file is not a valid .zip archive.'))

        Tx = self.env['revolut.transaction']
        Attachment = self.env['ir.attachment']
        company_id = self.env.company.id

        attached = skipped_dup = missing_tx = unparseable = 0
        tx_cache = {}

        for info in archive.infolist():
            if info.is_dir():
                continue
            basename = info.filename.rsplit('/', 1)[-1]
            if not basename or basename == 'manifest.csv':
                continue  # skip stray entries / a legacy manifest
            # <revolut_id>.<attachment_id>.<ext> — rsplit from the right so a
            # revolut_id that itself contains dots stays intact.
            parts = basename.rsplit('.', 2)
            revolut_id = parts[0].strip() if len(parts) == 3 else ''
            if not revolut_id:
                unparseable += 1
                continue

            tx = tx_cache.get(revolut_id)
            if tx is None:
                tx = Tx.search([
                    ('revolut_id', '=', revolut_id),
                    ('company_id', '=', company_id),
                ], limit=1)
                tx_cache[revolut_id] = tx
            if not tx:
                missing_tx += 1
                continue

            data = archive.read(info)
            sha1 = hashlib.sha1(data).hexdigest()
            if sha1 in tx.invoice_attachment_ids.mapped('checksum'):
                skipped_dup += 1
                continue

            att = Attachment.create({
                'name': basename,
                'type': 'binary',
                'datas': base64.b64encode(data),
                'mimetype': guess_mimetype(data, default='application/octet-stream'),
                'res_model': 'revolut.transaction',
                'res_id': tx.id,
            })
            tx.write({'invoice_attachment_ids': [(4, att.id)]})
            attached += 1

        msg = _('%s file(s) attached, %s duplicate(s) skipped, %s with no '
                'matching transaction, %s unparseable filename(s).') % (
            attached, skipped_dup, missing_tx, unparseable)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Import Bills'),
                'message': msg,
                'type': 'warning' if (missing_tx or unparseable) else 'success',
                'sticky': bool(missing_tx or unparseable),
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

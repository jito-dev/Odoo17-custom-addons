import base64
import csv
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
        """Read manifest.csv from the uploaded zip and re-attach each file to the
        matching transaction (by revolut_id, current company). Content-deduped,
        so re-importing the same zip is a no-op. Never creates bills."""
        self.ensure_one()
        if not self.zip_file:
            raise UserError(_('Please upload a .zip exported with "Export Bills".'))

        try:
            archive = zipfile.ZipFile(io.BytesIO(base64.b64decode(self.zip_file)))
        except zipfile.BadZipFile:
            raise UserError(_('The uploaded file is not a valid .zip archive.'))

        try:
            manifest = archive.read('manifest.csv').decode('utf-8')
        except KeyError:
            raise UserError(_('manifest.csv not found in the archive — is this a "Export Bills" zip?'))

        Tx = self.env['revolut.transaction']
        Attachment = self.env['ir.attachment']
        company_id = self.env.company.id

        attached = skipped_dup = missing_tx = missing_file = 0
        tx_cache = {}

        reader = csv.reader(io.StringIO(manifest))
        for i, row in enumerate(reader):
            if i == 0 or not row:
                continue  # header / blank
            revolut_id = (row[0] or '').strip()
            path = (row[1] or '').strip() if len(row) > 1 else ''
            if not revolut_id or not path:
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

            try:
                data = archive.read(path)
            except KeyError:
                missing_file += 1
                continue

            sha1 = hashlib.sha1(data).hexdigest()
            if sha1 in tx.invoice_attachment_ids.mapped('checksum'):
                skipped_dup += 1
                continue

            name = path.rsplit('/', 1)[-1]
            att = Attachment.create({
                'name': name,
                'type': 'binary',
                'datas': base64.b64encode(data),
                'mimetype': guess_mimetype(data, default='application/octet-stream'),
                'res_model': 'revolut.transaction',
                'res_id': tx.id,
            })
            tx.write({'invoice_attachment_ids': [(4, att.id)]})
            attached += 1

        msg = _('%s file(s) attached, %s duplicate(s) skipped, %s row(s) with no '
                'matching transaction, %s file(s) missing in zip.') % (
            attached, skipped_dup, missing_tx, missing_file)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Import Bills'),
                'message': msg,
                'type': 'warning' if (missing_tx or missing_file) else 'success',
                'sticky': bool(missing_tx or missing_file),
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

import html
import io
import logging
import re
import zipfile
from datetime import datetime

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Reuse the same structured schema/prompt as the vendor-bill AI extractor.
from odoo.addons.jito_invoice_extract_ai.models.openai_prompts import (  # noqa: E402
    InvoiceExtraction,
    INVOICE_EXTRACTION_PROMPT,
)

MAX_BILLS = 10
DOCX_MIME = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
# Minimum score for a bill to be *proposed* against a transaction.
PROPOSE_THRESHOLD = 35


class RevolutBillMatchWizard(models.TransientModel):
    _name = 'revolut.bill.match.wizard'
    _description = 'Upload & Match Bills to Revolut transactions'

    state = fields.Selection(
        [('upload', 'Upload'), ('review', 'Review'), ('done', 'Done')],
        default='upload', required=True)

    transaction_ids = fields.Many2many(
        'revolut.transaction', string='Selected Transactions')
    transaction_count = fields.Integer(
        compute='_compute_transaction_count')
    bill_attachment_ids = fields.Many2many(
        'ir.attachment', 'revolut_bill_match_wizard_att_rel',
        'wizard_id', 'attachment_id', string='Bills (PDF / image / DOCX)')

    line_ids = fields.One2many('revolut.bill.match.line', 'wizard_id')
    current_index = fields.Integer(default=0)

    # ── Stepper mirrors of the current line ──────────────────────────────────
    current_line_id = fields.Many2one(
        'revolut.bill.match.line', compute='_compute_current')
    current_position = fields.Integer(compute='_compute_current')
    total_count = fields.Integer(compute='_compute_current')
    attached_count = fields.Integer(compute='_compute_current')
    skipped_count = fields.Integer(compute='_compute_current')
    current_bill_name = fields.Char(compute='_compute_current')
    current_preview_html = fields.Html(compute='_compute_current', sanitize=False)
    current_extracted_vendor = fields.Char(compute='_compute_current')
    current_extracted_amount = fields.Float(compute='_compute_current', digits=(16, 2))
    current_extracted_currency = fields.Char(compute='_compute_current')
    current_extracted_date = fields.Date(compute='_compute_current')
    current_extracted_invoice_number = fields.Char(compute='_compute_current')
    current_proposed_transaction_id = fields.Many2one(
        'revolut.transaction', compute='_compute_current')
    current_confidence = fields.Selection(
        [('high', 'High'), ('medium', 'Medium'), ('low', 'Low'), ('none', 'No match')],
        compute='_compute_current')
    current_match_reasons = fields.Text(compute='_compute_current')
    current_has_proposal = fields.Boolean(compute='_compute_current')

    @api.depends('transaction_ids')
    def _compute_transaction_count(self):
        for wiz in self:
            wiz.transaction_count = len(wiz.transaction_ids)

    @api.depends('line_ids', 'line_ids.status', 'current_index')
    def _compute_current(self):
        for wiz in self:
            lines = wiz.line_ids
            wiz.total_count = len(lines)
            wiz.attached_count = len(lines.filtered(lambda l: l.status == 'attached'))
            wiz.skipped_count = len(lines.filtered(lambda l: l.status == 'skipped'))
            line = lines[wiz.current_index] if 0 <= wiz.current_index < len(lines) else lines.browse()
            wiz.current_line_id = line
            wiz.current_position = wiz.current_index + 1 if line else 0
            wiz.current_bill_name = line.bill_name
            wiz.current_extracted_vendor = line.extracted_vendor
            wiz.current_extracted_amount = line.extracted_amount
            wiz.current_extracted_currency = line.extracted_currency
            wiz.current_extracted_date = line.extracted_date
            wiz.current_extracted_invoice_number = line.extracted_invoice_number
            wiz.current_proposed_transaction_id = line.proposed_transaction_id
            wiz.current_confidence = line.confidence or 'none'
            wiz.current_match_reasons = line.match_reasons
            wiz.current_has_proposal = bool(line.proposed_transaction_id)
            wiz.current_preview_html = self._preview_html(line.attachment_id)

    # ── Preview ──────────────────────────────────────────────────────────────
    @staticmethod
    def _preview_html(attachment):
        if not attachment:
            return ''
        mimetype = (attachment.mimetype or '').lower()
        name = html.escape(attachment.name or 'file')
        if mimetype.startswith('image/'):
            return (
                f'<img src="/web/image/ir.attachment/{attachment.id}/datas" '
                f'style="max-width:100%;max-height:340px;object-fit:contain;'
                f'border:1px solid #dee2e6;border-radius:4px;"/>'
            )
        if mimetype == 'application/pdf':
            return (
                f'<iframe src="/web/content/{attachment.id}?download=false#toolbar=0" '
                f'style="width:100%;height:360px;border:1px solid #dee2e6;border-radius:4px;"></iframe>'
            )
        return (
            f'<a href="/web/content/{attachment.id}?download=false" target="_blank" '
            f'class="btn btn-secondary btn-sm"><i class="fa fa-file-o me-1"></i>Open {name}</a>'
        )

    # ── Step 1 → 2: extract + match ──────────────────────────────────────────
    def action_extract_and_match(self):
        self.ensure_one()
        if not self.bill_attachment_ids:
            raise UserError(_("Please upload at least one bill."))
        if not self.transaction_ids:
            raise UserError(_("No transactions selected to match against."))
        if len(self.bill_attachment_ids) > MAX_BILLS:
            raise UserError(_(
                "Please upload at most %s bills at a time (got %s).",
                MAX_BILLS, len(self.bill_attachment_ids)))

        api_key, model = self._get_openai_credentials()
        if not api_key:
            raise UserError(_(
                "OpenAI API key is not configured. Set it on the company "
                "(Settings → Accounting) or in this module's OpenAI Config."))

        try:
            import openai
        except ImportError:
            raise UserError(_(
                "The 'openai' Python package is not installed on the server."))
        client = openai.OpenAI(api_key=api_key)

        # 1) Extract each bill's data.
        bills = []
        for att in self.bill_attachment_ids:
            data, err = self._extract_bill(att, client, model)
            bills.append({'attachment': att, 'data': data, 'error': err})

        # 2) Propose a 1:1 assignment against the selected transactions.
        proposals = self._propose_matches(bills)

        # 3) Materialise the per-bill review lines.
        self.line_ids.unlink()
        line_vals = []
        for seq, b in enumerate(bills):
            p = proposals.get(id(b))
            data = b['data']
            line_vals.append((0, 0, {
                'sequence': (seq + 1) * 10,
                'attachment_id': b['attachment'].id,
                'bill_name': b['attachment'].name,
                'extracted_vendor': data.get('vendor') if data else False,
                'extracted_amount': data.get('amount') if data else 0.0,
                'extracted_currency': data.get('currency') if data else False,
                'extracted_date': data.get('date') if data else False,
                'extracted_invoice_number': data.get('invoice_number') if data else False,
                'extract_error': b['error'] or False,
                'proposed_transaction_id': p['tx'].id if p else False,
                'confidence': p['confidence'] if p else 'none',
                'match_reasons': (p['reasons'] if p else (
                    b['error'] or _("No confident match among the selected transactions."))),
            }))
        self.write({'line_ids': line_vals, 'state': 'review', 'current_index': 0})
        return self._reload()

    def _get_openai_credentials(self):
        company = self.env.company
        api_key = (company.openai_api_key or '').strip()
        model = (company.openai_model or '').strip()
        if not api_key:
            cfg = self.env['openai.config'].sudo().search(
                [('company_id', '=', company.id)], limit=1)
            if cfg:
                api_key = (cfg.api_key or '').strip()
                model = model or (cfg.model_name or '')
        return api_key, (model or 'gpt-4o')

    # ── AI extraction (mirrors jito_invoice_extract_ai) ──────────────────────
    def _extract_bill(self, attachment, client, model):
        """Return (data_dict, error_str). data_dict has amount/currency/date/
        vendor/invoice_number, or None on failure."""
        if not attachment.datas:
            return None, _("Empty file.")
        mimetype = (attachment.mimetype or '').lower()
        _logger.warning(
            "OPENAI DIGITIZATION: extracting uploaded bill '%s' (%s) for matching",
            attachment.name, mimetype)
        try:
            if mimetype == DOCX_MIME or (attachment.name or '').lower().endswith('.docx'):
                text = self._docx_to_text(attachment.datas)
                if not text.strip():
                    return None, _("Could not read text from the DOCX file.")
                user_content = [{
                    "type": "input_text",
                    "text": "Extract all data from this invoice:\n\n" + text[:120000],
                }]
            else:
                base64_string = attachment.datas.decode('utf-8')
                file_data_uri = f"data:{attachment.mimetype};base64,{base64_string}"
                if mimetype.startswith('image/'):
                    file_content = {"type": "input_image", "image_url": file_data_uri}
                else:
                    file_content = {
                        "type": "input_file",
                        "filename": attachment.name or "invoice.pdf",
                        "file_data": file_data_uri,
                    }
                user_content = [
                    file_content,
                    {"type": "input_text", "text": "Extract all data from this invoice."},
                ]

            response = client.responses.parse(
                model=model,
                input=[
                    {"role": "system", "content": INVOICE_EXTRACTION_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                text_format=InvoiceExtraction,
            )
            result = getattr(response, 'output_parsed', None) or getattr(response, 'parsed', None)
            if not result:
                return None, _("OpenAI returned an unparseable response.")
            return self._normalise_extraction(result), None
        except Exception as e:  # noqa: BLE001 — surfaced per-bill, never aborts the batch
            _logger.exception("Bill extraction failed for %s", attachment.name)
            return None, _("Extraction failed: %s", str(e)[:200])

    @staticmethod
    def _normalise_extraction(result):
        def parse_date(val):
            if not val:
                return False
            try:
                return datetime.strptime(val[:10], '%Y-%m-%d').date()
            except (ValueError, TypeError):
                return False
        vendor = getattr(result, 'vendor', None)
        return {
            'amount': getattr(result, 'total_amount', None) or 0.0,
            'currency': (getattr(result, 'currency', None) or '').upper() or False,
            'date': parse_date(getattr(result, 'invoice_date', None))
                    or parse_date(getattr(result, 'due_date', None)),
            'vendor': getattr(vendor, 'name', None) if vendor else False,
            'invoice_number': getattr(result, 'invoice_number', None) or False,
        }

    @staticmethod
    def _docx_to_text(datas):
        import base64
        raw = base64.b64decode(datas)
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            xml = z.read('word/document.xml').decode('utf-8', errors='ignore')
        # Preserve paragraph / tab boundaries, then strip tags.
        xml = xml.replace('</w:p>', '\n').replace('<w:tab/>', '\t')
        text = re.sub(r'<[^>]+>', '', xml)
        return html.unescape(text)

    # ── Deterministic 1:1 matcher ────────────────────────────────────────────
    def _propose_matches(self, bills):
        """Greedy 1:1 assignment of bills to selected transactions. Returns
        {id(bill): {'tx', 'confidence', 'reasons'}}."""
        scored = []  # (score, signals, reasons, id(bill), tx)
        for b in bills:
            if not b['data']:
                continue
            for tx in self.transaction_ids:
                score, reasons, signals = self._score(b['data'], tx)
                if score >= PROPOSE_THRESHOLD:
                    scored.append((score, signals, reasons, id(b), tx))
        scored.sort(key=lambda s: s[0], reverse=True)

        proposals = {}
        used_tx = set()
        for score, signals, reasons, bid, tx in scored:
            if bid in proposals or tx.id in used_tx:
                continue
            proposals[bid] = {
                'tx': tx,
                'confidence': self._confidence(score, signals),
                'reasons': "\n".join(reasons),
            }
            used_tx.add(tx.id)
        return proposals

    @staticmethod
    def _confidence(score, signals):
        if signals.get('amount_strong') and (signals.get('currency') or signals.get('date_strong')) \
                and score >= 60:
            return 'high'
        if score >= 45:
            return 'medium'
        return 'low'

    @staticmethod
    def _score(data, tx):
        reasons = []
        signals = {}
        score = 0

        # Amount — compare |bill total| against |tx.amount| and |tx.bill_amount|.
        be = abs(data.get('amount') or 0.0)
        cands = [abs(tx.amount or 0.0), abs(tx.bill_amount or 0.0)]
        cands = [c for c in cands if c > 0]
        if be > 0 and cands:
            abs_diff = min(abs(be - c) for c in cands)
            ratio = min(abs(be - c) / max(be, 0.01) for c in cands)
            if abs_diff <= 0.01:
                score += 50
                signals['amount_strong'] = True
                reasons.append(_("✓ Amount matches: %.2f", be))
            elif ratio <= 0.01:
                score += 40
                signals['amount_strong'] = True
                reasons.append(_("✓ Amount matches: ~%.2f", be))
            elif ratio <= 0.05:
                score += 18
                reasons.append(_("≈ Amount close: bill %.2f vs tx %.2f", be, min(cands, key=lambda c: abs(be - c))))

        # Currency.
        bc = (data.get('currency') or '').upper()
        tx_currencies = {(tx.currency or '').upper(), (tx.bill_currency or '').upper()}
        if bc and bc in tx_currencies:
            score += 20
            signals['currency'] = True
            reasons.append(_("✓ Currency matches: %s", bc))

        # Date — bill invoice date vs settlement date.
        bd = data.get('date')
        td = tx.settlement_date_local or tx.settlement_date
        if bd and td:
            delta = abs((bd - td).days)
            if delta <= 3:
                score += 20
                signals['date_strong'] = True
                reasons.append(_("✓ Dates match: invoice %s vs tx %s (%s day(s))", bd, td, delta))
            elif delta <= 7:
                score += 12
                reasons.append(_("✓ Dates close: invoice %s vs tx %s (%s days)", bd, td, delta))
            elif delta <= 31:
                score += 5
                reasons.append(_("≈ Same month: invoice %s vs tx %s (%s days)", bd, td, delta))

        # Vendor — token overlap against merchant + description.
        vendor = (data.get('vendor') or '').lower()
        hay = ((tx.merchant_name or '') + ' ' + (tx.description or '')).lower()
        if vendor and hay.strip():
            vtokens = {t for t in re.split(r'\W+', vendor) if len(t) > 2}
            htokens = {t for t in re.split(r'\W+', hay) if len(t) > 2}
            overlap = vtokens & htokens
            if overlap:
                score += min(15, 5 * len(overlap))
                reasons.append(_("✓ Vendor matches: %s", ", ".join(sorted(overlap))))

        return score, reasons, signals

    # ── Step 2: attach / skip / advance ──────────────────────────────────────
    def action_attach_current(self):
        self.ensure_one()
        line = self.current_line_id
        if not line or not line.proposed_transaction_id or not line.attachment_id:
            return self._advance()
        attachment = line.attachment_id.sudo()
        tx = line.proposed_transaction_id
        # Own the attachment by the transaction (ACL + preview), then link it.
        attachment.write({'res_model': 'revolut.transaction', 'res_id': tx.id})
        tx.write({'invoice_attachment_ids': [(4, attachment.id)]})
        line.status = 'attached'
        return self._advance()

    def action_skip_current(self):
        self.ensure_one()
        if self.current_line_id:
            self.current_line_id.status = 'skipped'
        return self._advance()

    def _advance(self):
        self.current_index += 1
        if self.current_index >= len(self.line_ids):
            self.state = 'done'
        return self._reload()

    def _reload(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': self.env.context,
        }

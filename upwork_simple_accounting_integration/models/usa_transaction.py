import base64
import json
import logging
import re
from datetime import datetime

import odoo
from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class UsaTransaction(models.Model):
    """Upwork transaction row from transactionHistory GraphQL query."""

    _name = 'usa.transaction'
    _description = 'Upwork Transaction'
    _inherit = ['mail.thread']
    # "Date" everywhere means Upwork's ledger (review-due) date, so order by it.
    _order = 'transaction_review_due_date desc, row_number asc'

    # ── Identification ────────────────────────────────────────────────────────

    record_id = fields.Char(
        string='Record ID',
        index=True,
        copy=False,
        readonly=True,
    )
    row_number = fields.Integer(string='Row #', readonly=True)

    # ── Dates ─────────────────────────────────────────────────────────────────

    transaction_creation_date = fields.Datetime(string='Creation Date', readonly=True)
    transaction_review_due_date = fields.Datetime(string='Review Due Date', readonly=True)
    fully_paid_date = fields.Datetime(string='Fully Paid Date', readonly=True)

    # ── Type / Classification ─────────────────────────────────────────────────

    transaction_type = fields.Char(string='Type', readonly=True)
    accounting_subtype = fields.Char(string='Subtype', readonly=True)
    payment_status = fields.Char(string='Payment Status', readonly=True)
    payment_guaranteed = fields.Boolean(string='Payment Guaranteed', readonly=True)
    prefix = fields.Char(string='Prefix', readonly=True)

    # ── Amounts ───────────────────────────────────────────────────────────────

    transaction_amount_raw = fields.Float(
        string='Transaction Amount', digits=(16, 2), readonly=True)
    transaction_amount_currency = fields.Char(string='Amount Currency', readonly=True)

    amount_credited_raw = fields.Float(
        string='Amount Credited to User', digits=(16, 2), readonly=True)
    amount_credited_currency = fields.Char(string='Credited Currency', readonly=True)

    running_balance_raw = fields.Float(
        string='Running Balance', digits=(16, 2), readonly=True)
    running_balance_currency = fields.Char(string='Balance Currency', readonly=True)

    amount_sent_orig_raw = fields.Float(
        string='Amount Sent (Orig Currency)', digits=(16, 2), readonly=True)
    amount_sent_orig_currency = fields.Char(string='Sent Currency', readonly=True)

    payment_raw = fields.Float(
        string='Payment', digits=(16, 2), readonly=True)
    payment_currency = fields.Char(string='Payment Currency', readonly=True)

    remainder = fields.Char(string='Remainder', readonly=True)

    # ── Description ───────────────────────────────────────────────────────────

    description = fields.Text(string='Description', readonly=True)
    description_ui = fields.Char(string='Description (UI)', readonly=True)
    purchase_order_number = fields.Char(string='Purchase Order Number', readonly=True)

    # ── Parsed Description ────────────────────────────────────────────────────
    # Pattern: "(41846002) Jersey Watch/Kyrylo Shelipov - 45:00 hrs @ $50.00/hr - 03/02/2026 - 03/08/2026"

    parsed_contract_id = fields.Char(
        string='Contract ID', compute='_compute_parsed_description',
        store=True, readonly=True, copy=False)
    parsed_hours = fields.Float(
        string='Hours', digits=(8, 2), compute='_compute_parsed_description',
        store=True, readonly=True, copy=False)
    parsed_rate = fields.Float(
        string='Rate ($/hr)', digits=(8, 2), compute='_compute_parsed_description',
        store=True, readonly=True, copy=False)
    amount_of_hours = fields.Char(
        string='Amount of Hours',
        compute='_compute_parsed_description',
        store=True, readonly=True, copy=False,
        help='Raw hours string extracted from description, e.g. "45:00".',
    )
    parsed_period_start = fields.Date(
        string='Period Start', compute='_compute_parsed_description',
        store=True, readonly=True, copy=False)
    parsed_period_end = fields.Date(
        string='Period End', compute='_compute_parsed_description',
        store=True, readonly=True, copy=False)

    @api.depends('description')
    def _compute_parsed_description(self):
        for rec in self:
            parsed = rec._parse_description(rec.description or '')
            rec.parsed_contract_id = parsed.get('contract_id', False)
            rec.parsed_hours = parsed.get('hours', 0.0)
            rec.parsed_rate = parsed.get('rate', 0.0)
            rec.amount_of_hours = parsed.get('amount_of_hours', False)
            rec.parsed_period_start = parsed.get('period_start', False)
            rec.parsed_period_end = parsed.get('period_end', False)

    @staticmethod
    def _parse_description(text):
        """Parse an Upwork hourly billing description into structured fields.

        Expected format:
        (41846002) Jersey Watch/Kyrylo Shelipov - 45:00 hrs @ $50.00/hr - 03/02/2026 - 03/08/2026
        Returns a dict with keys: contract_id, hours, rate, period_start, period_end.
        Returns empty dict on no match.
        """
        result = {}
        if not text:
            return result

        # Contract ID: first occurrence of digits inside parentheses
        m = re.search(r'\((\d+)\)', text)
        if m:
            result['contract_id'] = m.group(1)

        # Hours: HH:MM hrs  →  float hours + raw string
        m = re.search(r'(\d+):(\d+)\s+hrs', text)
        if m:
            result['hours'] = int(m.group(1)) + int(m.group(2)) / 60.0
            result['amount_of_hours'] = f"{m.group(1)}:{m.group(2)}"

        # Rate: $XX.XX/hr
        m = re.search(r'\$(\d+(?:\.\d+)?)/hr', text)
        if m:
            result['rate'] = float(m.group(1))

        # Dates: MM/DD/YYYY — take first two occurrences
        dates = re.findall(r'(\d{2}/\d{2}/\d{4})', text)
        if len(dates) >= 1:
            try:
                result['period_start'] = datetime.strptime(dates[0], '%m/%d/%Y').date()
            except ValueError:
                pass
        if len(dates) >= 2:
            try:
                result['period_end'] = datetime.strptime(dates[1], '%m/%d/%Y').date()
            except ValueError:
                pass

        return result

    # ── Contract Detail link ──────────────────────────────────────────────────

    contract_detail_id = fields.Many2one(
        'usa.contract.detail',
        string='Contract Detail',
        readonly=True,
        ondelete='set null',
        copy=False,
    )

    # ── Relations ─────────────────────────────────────────────────────────────

    related_transaction_id = fields.Char(string='Related Transaction ID', readonly=True)
    related_invoice_id = fields.Char(string='Related Invoice ID', readonly=True)
    related_assignment = fields.Char(string='Related Assignment', readonly=True)
    related_accounting_entity = fields.Char(string='Related Accounting Entity', readonly=True)
    related_user_payment_method = fields.Char(string='Related Payment Method', readonly=True)
    fixed_price_earmark = fields.Char(string='Fixed Price Earmark', readonly=True)

    # ── Assignment Info ───────────────────────────────────────────────────────

    assignment_agency_name = fields.Char(string='Agency', readonly=True)
    assignment_company_name = fields.Char(string='Client Company', readonly=True)
    assignment_developer_name = fields.Char(string='Freelancer', readonly=True)
    assignment_team_id = fields.Char(string='Team ID', readonly=True)
    assignment_team_reference = fields.Char(string='Team Reference', readonly=True)
    assignment_team_company_id = fields.Char(string='Team Company ID', readonly=True)
    assignment_team_company_reference = fields.Char(string='Team Company Reference', readonly=True)
    assignment_team_user_id = fields.Char(string='Team User ID', readonly=True)
    assignment_team_user_reference = fields.Char(string='Team User Reference', readonly=True)

    # ── Upwork Invoice PDF ────────────────────────────────────────────────────

    upwork_invoice_pdf = fields.Binary(
        string='Upwork Invoice PDF', attachment=True, copy=False)
    upwork_invoice_filename = fields.Char(
        string='Invoice Filename', copy=False)
    has_upwork_invoice = fields.Boolean(
        string='Has Invoice',
        compute='_compute_has_upwork_invoice',
        store=True,
    )

    # ── Invoice Number ────────────────────────────────────────────────────────

    invoice_number = fields.Char(
        string='Invoice Number',
        copy=False,
        help='Invoice number to embed in the generated document.',
    )

    @api.depends('upwork_invoice_pdf')
    def _compute_has_upwork_invoice(self):
        for rec in self:
            rec.has_upwork_invoice = bool(rec.upwork_invoice_pdf)

    # ── Extracted Invoice Data ────────────────────────────────────────────────

    extracted_client_address = fields.Char(
        string='Client Billing Full Address', copy=False)
    extracted_client_zip = fields.Char(
        string='Client Billing ZIP', copy=False)
    extracted_client_country = fields.Char(
        string='Client Billing Country', copy=False)
    extracted_client_street = fields.Char(
        string='Client Billing Street', copy=False)
    extracted_client_city = fields.Char(
        string='Client Billing City', copy=False)
    extracted_client_state = fields.Char(
        string='Client Billing State', copy=False)

    extraction_state = fields.Selection(
        selection=[
            ('idle', 'Idle'),
            ('pending', 'Pending'),
            ('processing', 'Processing'),
            ('done', 'Done'),
            ('failed', 'Failed'),
        ],
        string='Extraction State',
        default='idle',
        copy=False,
    )
    extraction_status = fields.Char(
        string='Extraction Status', copy=False, readonly=True)

    # ── Accounting Injection ────────────────────────────────────────────────
    statement_line_id = fields.Many2one(
        'account.bank.statement.line',
        string='Statement Line',
        readonly=True, copy=False,
        ondelete='set null',
    )
    is_injected = fields.Boolean(
        string='Injected',
        compute='_compute_is_injected', store=True,
    )
    upwork_tx_ref = fields.Char(
        string='Upwork TX Ref',
        compute='_compute_upwork_tx_ref', store=True,
        index='trigram', readonly=True, copy=False,
    )

    @api.depends('statement_line_id')
    def _compute_is_injected(self):
        for rec in self:
            rec.is_injected = bool(rec.statement_line_id)

    @api.depends('record_id')
    def _compute_upwork_tx_ref(self):
        for rec in self:
            rec.upwork_tx_ref = rec.record_id or False

    # ── Meta ──────────────────────────────────────────────────────────────────

    raw_json = fields.Text(string='Raw JSON', readonly=True, copy=False)
    sync_date = fields.Datetime(string='Last Synced', readonly=True, copy=False)

    # ── Invoice Generation ────────────────────────────────────────────────────

    invoice_state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('generated', 'Generated'),
        ],
        string='Invoice Status',
        default='draft',
        tracking=True,
    )
    context_data = fields.Text(string='Invoice Context (JSON)', readonly=True, copy=False)
    rendered_vars_html = fields.Html(
        string='Template Variables',
        sanitize=False,
        readonly=True,
        copy=False,
    )
    generated_docx_id = fields.Many2one(
        'ir.attachment',
        string='Generated DOCX',
        ondelete='set null',
        copy=False,
    )
    generated_pdf_id = fields.Many2one(
        'ir.attachment',
        string='Generated PDF',
        ondelete='set null',
        copy=False,
    )

    # ── Invoice context builder ───────────────────────────────────────────────

    def action_build_invoice_context(self):
        """Build Jinja2 context for invoice template (ctx.client / ctx.inv / ctx.supplier)."""
        self.ensure_one()

        def _fmt_date(dt):
            return dt.strftime('%d.%m.%Y') if dt else ''

        inv_config = self.env['usa.invoice.config'].sudo()._get_singleton()
        company = self.env.company
        supplier_address = ', '.join(filter(None, [
            company.street,
            company.street2,
            company.city,
            company.state_id.name if company.state_id else '',
            company.zip,
            company.country_id.name if company.country_id else '',
        ]))

        amount   = self.transaction_amount_raw or 0.0
        credited = self.amount_credited_raw or 0.0
        currency = (self.transaction_amount_currency or 'USD').upper()

        _ctx = {
            'client': {
                'legal_name':    self.assignment_company_name or '',
                'legal_address': self.extracted_client_address or '',
            },
            'supplier': {
                'legal_name':    company.name or '',
                'legal_address': supplier_address,
                'vat':           company.vat or '',
            },
            'inv': {
                'number':         ('T' + self.related_invoice_id) if self.related_invoice_id else '',
                'transaction_id': self.record_id or '',
                'date':           _fmt_date(self.transaction_creation_date),
                'due_date':       _fmt_date(self.transaction_review_due_date),
                'description':    self.description_ui or self.description or '',
                'amount':         amount,
                'amt':            f'{amount:,.2f} {currency}',
                'total_amount':   amount,
                'total_due':      credited,
                'hourly_rate':    self.parsed_rate or 0.0,
                'hrs':            self.parsed_hours or 0.0,
                'amount_of_hours': self.amount_of_hours or '',
            },
        }

        # Wrap under 'ctx' so template variables like {{ ctx.client.legal_name }}
        # resolve correctly in both the preview table and Jinja2 render.
        ctx = {'ctx': _ctx}

        rendered_html = self._build_rendered_vars_html(ctx)
        self.write({
            'context_data':       json.dumps(ctx, default=str, indent=2),
            'rendered_vars_html': rendered_html,
        })
        return ctx

    def _build_rendered_vars_html(self, ctx):
        """Build HTML table showing Jinja2 variables resolved from ctx using invoice config template."""
        config = self.env['usa.invoice.config'].sudo()._get_singleton()
        if not config or not config.inv_uploaded:
            return False

        from odoo.addons.jito_document_template.services.docx_renderer import (  # noqa: PLC0415
            extract_jinja_variables, build_rendered_vars_html)

        file_b64 = config.with_context(bin_size=False).inv_template_file
        if not file_b64:
            return False
        try:
            variables = extract_jinja_variables(base64.b64decode(file_b64))
            return build_rendered_vars_html(variables, ctx)
        except Exception as exc:
            return '<p class="text-danger small">Could not parse template: %s</p>' % str(exc)

    # ── Invoice generation ────────────────────────────────────────────────────

    def action_generate_invoice(self):
        """Render DOCX (+ PDF if LibreOffice available) from transaction data."""
        self.ensure_one()
        from odoo.addons.jito_document_template.services.docx_renderer import (  # noqa: PLC0415
            render_docx, convert_to_pdf, is_libreoffice_available)

        config = self.env['usa.invoice.config'].sudo()._get_singleton()
        if not config or not config.inv_uploaded:
            raise UserError(_(
                'No invoice template uploaded. '
                'Please upload a DOCX template in Configuration → Invoice Generation.'
            ))

        file_b64 = config.with_context(bin_size=False).inv_template_file
        if not file_b64:
            raise UserError(_('No invoice template file found.'))

        ctx = self.action_build_invoice_context()
        docx_bytes = render_docx(base64.b64decode(file_b64), ctx)

        def _resolve_name(ext):
            src = self.upwork_invoice_filename or ''
            if src:
                base = src.rsplit('.', 1)[0] if '.' in src else src
                return '%s_generated.%s' % (base, ext)
            return 'invoice_%s_generated.%s' % (self.record_id or self.id, ext)

        docx_att = self.env['ir.attachment'].create({
            'name': _resolve_name('docx'),
            'datas': base64.b64encode(docx_bytes),
            'mimetype': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'res_model': self._name,
            'res_id': self.id,
        })

        pdf_att = False
        if is_libreoffice_available():
            try:
                pdf_bytes = convert_to_pdf(docx_bytes)
                pdf_att = self.env['ir.attachment'].create({
                    'name': _resolve_name('pdf'),
                    'datas': base64.b64encode(pdf_bytes),
                    'mimetype': 'application/pdf',
                    'res_model': self._name,
                    'res_id': self.id,
                })
            except Exception as exc:
                _logger.warning('PDF conversion failed for transaction %s: %s', self.record_id, exc)

        self.write({
            'generated_docx_id': docx_att.id,
            'generated_pdf_id': pdf_att.id if pdf_att else False,
            'invoice_state': 'generated',
        })

    def action_download_docx(self):
        self.ensure_one()
        if not self.generated_docx_id:
            raise UserError(_('No DOCX file generated yet.'))
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%d?download=true' % self.generated_docx_id.id,
            'target': 'self',
        }

    def action_download_pdf(self):
        self.ensure_one()
        if not self.generated_pdf_id:
            raise UserError(_('No PDF file generated yet.'))
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%d?download=true' % self.generated_pdf_id.id,
            'target': 'self',
        }

    def action_reset_invoice(self):
        """Reset invoice generation state."""
        self.ensure_one()
        if self.generated_docx_id:
            self.generated_docx_id.sudo().unlink()
        if self.generated_pdf_id:
            self.generated_pdf_id.sudo().unlink()
        self.write({
            'invoice_state': 'draft',
            'generated_docx_id': False,
            'generated_pdf_id': False,
            'context_data': False,
            'rendered_vars_html': False,
        })

    # ── Upwork Invoice Actions ────────────────────────────────────────────────

    def action_download_upwork_invoice(self):
        self.ensure_one()
        if not self.upwork_invoice_pdf:
            raise UserError(_('No invoice PDF attached.'))
        filename = self.upwork_invoice_filename or 'invoice.pdf'
        att = self.env['ir.attachment'].search([
            ('res_model', '=', self._name),
            ('res_id', '=', self.id),
            ('res_field', '=', 'upwork_invoice_pdf'),
        ], limit=1)
        if att:
            return {
                'type': 'ir.actions.act_url',
                'url': '/web/content/%d/%s?download=true' % (att.id, filename),
                'target': 'self',
            }
        # Fallback: serve via binary controller
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/usa.transaction/%d/upwork_invoice_pdf/%s?download=true' % (
                self.id, filename),
            'target': 'self',
        }

    def action_remove_upwork_invoice(self):
        self.ensure_one()
        self.write({'upwork_invoice_pdf': False, 'upwork_invoice_filename': False})

    # ── OpenAI extraction ────────────────────────────────────────────────────

    def _extract_data_from_invoice_core(self):
        """Call OpenAI to extract billing address fields from the attached PDF.

        Returns a dict with keys:
            client_billing_full_address, client_billing_zip, client_billing_country
        Raises exceptions (including UserError) on any failure.
        """
        import urllib.error as _urllib_error
        import urllib.request as _urllib_request
        import uuid as _uuid

        self.ensure_one()

        config = self.env['usa.openai.config'].sudo()._get_singleton()
        if not (config.api_key or '').strip():
            raise UserError(_(
                'OpenAI API key is not configured. '
                'Go to Configuration → OpenAI Configuration to set it up.'
            ))

        headers = config._get_headers()

        # ── Step 1: Decode PDF binary ─────────────────────────────────────
        pdf_bytes = base64.b64decode(
            self.with_context(bin_size=False).upwork_invoice_pdf
        )
        filename = self.upwork_invoice_filename or 'invoice.pdf'

        # ── Step 2: Upload PDF to OpenAI Files API ────────────────────────
        boundary = _uuid.uuid4().hex
        multipart_body = (
            b'--' + boundary.encode() + b'\r\n'
            b'Content-Disposition: form-data; name="purpose"\r\n\r\nuser_data\r\n'
            b'--' + boundary.encode() + b'\r\n'
            b'Content-Disposition: form-data; name="file"; filename="'
            + filename.encode() + b'"\r\n'
            b'Content-Type: application/pdf\r\n\r\n'
            + pdf_bytes + b'\r\n'
            b'--' + boundary.encode() + b'--\r\n'
        )
        upload_req = _urllib_request.Request(
            'https://api.openai.com/v1/files',
            data=multipart_body,
            headers={
                'Authorization': headers['Authorization'],
                'Content-Type': f'multipart/form-data; boundary={boundary}',
            },
            method='POST',
        )
        try:
            with _urllib_request.urlopen(upload_req, timeout=60) as resp:
                upload_data = json.loads(resp.read().decode())
        except _urllib_error.HTTPError as e:
            body = e.read().decode()
            try:
                msg = json.loads(body).get('error', {}).get('message', body)
            except Exception:
                msg = body[:300]
            raise UserError(_('OpenAI file upload failed: %s') % msg)
        except Exception as e:
            raise UserError(_('OpenAI file upload failed: %s') % str(e))

        file_id = upload_data.get('id')
        if not file_id:
            raise UserError(_('OpenAI did not return a file ID after upload.'))

        # ── Step 3: Chat completion — extract billing fields ──────────────
        prompt = (
            'You are a data extraction assistant. '
            'From the attached Upwork invoice PDF, extract the CLIENT (buyer/employer) '
            'billing address as SEPARATE components — do not merge them. '
            'Return ONLY valid JSON with these exact keys: '
            '"client_billing_street" (street line incl. apartment/suite, e.g. "1141 Salem Drive Apt C"), '
            '"client_billing_city", '
            '"client_billing_state" (state/province name or code), '
            '"client_billing_zip", '
            '"client_billing_country" (full country name), '
            '"client_billing_full_address" (the complete address on one human-readable line). '
            'If a field cannot be found, use an empty string. '
            'Do not include any explanation or markdown — raw JSON only.'
        )
        chat_payload = json.dumps({
            'model': config.model_name,
            'messages': [{
                'role': 'user',
                'content': [
                    {'type': 'file', 'file': {'file_id': file_id}},
                    {'type': 'text', 'text': prompt},
                ],
            }],
        }).encode()
        chat_req = _urllib_request.Request(
            'https://api.openai.com/v1/chat/completions',
            data=chat_payload,
            headers=headers,
            method='POST',
        )
        try:
            with _urllib_request.urlopen(chat_req, timeout=60) as resp:
                chat_data = json.loads(resp.read().decode())
        except _urllib_error.HTTPError as e:
            body = e.read().decode()
            try:
                msg = json.loads(body).get('error', {}).get('message', body)
            except Exception:
                msg = body[:300]
            raise UserError(_('OpenAI extraction failed: %s') % msg)
        except Exception as e:
            raise UserError(_('OpenAI extraction failed: %s') % str(e))
        finally:
            # ── Step 4: Delete uploaded file from OpenAI (cleanup) ────────
            try:
                del_req = _urllib_request.Request(
                    f'https://api.openai.com/v1/files/{file_id}',
                    headers={'Authorization': headers['Authorization']},
                    method='DELETE',
                )
                _urllib_request.urlopen(del_req, timeout=10)
            except Exception:
                _logger.warning('Failed to delete OpenAI file %s during cleanup', file_id)

        raw_content = (
            chat_data.get('choices', [{}])[0]
            .get('message', {})
            .get('content', '')
            .strip()
        )

        # Strip markdown code fences if present
        if raw_content.startswith('```'):
            raw_content = '\n'.join(
                line for line in raw_content.splitlines()
                if not line.startswith('```')
            ).strip()

        try:
            return json.loads(raw_content)
        except Exception:
            raise UserError(_(
                'Could not parse OpenAI response as JSON.\nResponse: %s'
            ) % raw_content[:500])

    def _apply_extracted(self, extracted):
        """Store the structured extraction result onto the extracted_* fields."""
        self.write({
            'extracted_client_street': extracted.get('client_billing_street', '') or '',
            'extracted_client_city': extracted.get('client_billing_city', '') or '',
            'extracted_client_state': extracted.get('client_billing_state', '') or '',
            'extracted_client_zip': extracted.get('client_billing_zip', '') or '',
            'extracted_client_country': extracted.get('client_billing_country', '') or '',
            'extracted_client_address': extracted.get('client_billing_full_address', '') or '',
        })

    def action_extract_data_from_invoice(self):
        """Synchronous single-record extraction (form view button)."""
        self.ensure_one()
        if not self.upwork_invoice_pdf:
            raise UserError(_('No invoice PDF attached.'))

        extracted = self._extract_data_from_invoice_core()
        self._apply_extracted(extracted)
        self.write({
            'extraction_state': 'done',
            'extraction_status': _('Extracted successfully.'),
        })
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Extraction Complete'),
                'message': _('Billing data extracted successfully from the invoice PDF.'),
                'type': 'success',
            },
        }

    def _run_extract_job(self, user_id):
        """Background job worker (queue_job). Called via with_delay()."""
        self.ensure_one()
        self.write({
            'extraction_state': 'processing',
            'extraction_status': _('Processing: calling OpenAI API…'),
        })
        try:
            extracted = self._extract_data_from_invoice_core()
            self._apply_extracted(extracted)
            self.write({
                'extraction_state': 'done',
                'extraction_status': _('Done.'),
            })
            self._notify_user(user_id, {
                'title': _('Extraction Complete'),
                'message': _('Invoice data extracted for transaction %s.') % (self.record_id or self.id),
                'type': 'success',
                'sticky': False,
            })
        except Exception as exc:
            self.write({
                'extraction_state': 'failed',
                'extraction_status': str(exc)[:255],
            })
            self._notify_user(user_id, {
                'title': _('Extraction Failed'),
                'message': _('Failed for transaction %s: %s') % (self.record_id or self.id, str(exc)[:200]),
                'type': 'danger',
                'sticky': True,
            })
            raise

    @api.model
    def _notify_user(self, user_id, params):
        """Send a non-blocking bus notification to a specific user."""
        try:
            with odoo.registry(self.env.cr.dbname).cursor() as notify_cr:
                notify_env = api.Environment(notify_cr, self.env.uid, self.env.context)
                user = notify_env['res.users'].browse(user_id)
                if user.partner_id:
                    notify_env['bus.bus']._sendone(
                        user.partner_id, 'simple_notification', params
                    )
                notify_cr.commit()
        except Exception as e:
            _logger.error('Failed to send notification to user %s: %s', user_id, e)

    # ── Contract Details ──────────────────────────────────────────────────────

    def action_request_contract_details(self):
        """Fetch contractDetails from Upwork and link to this transaction."""
        self.ensure_one()
        if not self.parsed_contract_id:
            raise UserError(_(
                'No Contract ID found in the transaction description. '
                'Only hourly billing transactions have a parseable contract ID.'
            ))
        detail = self.env['usa.contract.detail'].fetch_and_save(self.parsed_contract_id)
        self.write({'contract_detail_id': detail.id})
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'usa.contract.detail',
            'res_id': detail.id,
            'view_mode': 'form',
            'target': 'current',
        }

    # ── Batch Actions (list view) ──────────────────────────────────────────────

    def action_batch_request_contract_details(self):
        """Batch: fetch contract details for selected transactions."""
        success, skipped = 0, 0
        for rec in self:
            if not rec.parsed_contract_id:
                skipped += 1
                continue
            try:
                detail = self.env['usa.contract.detail'].fetch_and_save(rec.parsed_contract_id)
                rec.write({'contract_detail_id': detail.id})
                success += 1
            except Exception as exc:
                _logger.warning('Batch contract details failed for %s: %s', rec.record_id, exc)
                skipped += 1
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Request Contract Details'),
                'message': _('%d processed, %d skipped.') % (success, skipped),
                'type': 'success' if success else 'warning',
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    def action_batch_extract_data_from_invoice(self):
        """Batch: enqueue background AI extraction jobs for selected transactions."""
        to_process = self.filtered(lambda r: r.upwork_invoice_pdf)
        skipped = len(self) - len(to_process)
        if not to_process:
            raise UserError(_('None of the selected transactions have an attached invoice PDF.'))

        to_process.write({
            'extraction_state': 'pending',
            'extraction_status': _('Pending: queued for AI extraction…'),
        })

        user_id = self.env.user.id
        for rec in to_process:
            rec.with_delay()._run_extract_job(user_id)

        msg = _('%d transaction(s) queued for AI extraction in the background.') % len(to_process)
        if skipped:
            msg += ' ' + _('%d skipped (no PDF attached).') % skipped
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Extraction Queued'),
                'message': msg,
                'type': 'info',
                'sticky': False,
            },
        }

    def action_batch_remove_upwork_invoice(self):
        """Batch: remove the attached Upwork invoice PDF from selected transactions."""
        to_clear = self.filtered(lambda r: r.upwork_invoice_pdf)
        skipped = len(self) - len(to_clear)
        to_clear.write({'upwork_invoice_pdf': False, 'upwork_invoice_filename': False})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Files Removed'),
                'message': _('%d file(s) removed, %d had no attachment.') % (len(to_clear), skipped),
                'type': 'success' if to_clear else 'warning',
            },
        }

    def action_batch_generate_invoice(self):
        """Batch: generate custom invoice DOCX/PDF for selected transactions."""
        success, skipped = 0, 0
        for rec in self:
            try:
                rec.action_generate_invoice()
                success += 1
            except Exception as exc:
                _logger.warning('Batch invoice generation failed for %s: %s', rec.record_id, exc)
                skipped += 1
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Generate Custom Invoice'),
                'message': _('%d generated, %d failed.') % (success, skipped),
                'type': 'success' if success else 'warning',
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    # ── Accounting Injection ─────────────────────────────────────────────────

    move_id = fields.Many2one(
        'account.move', string='Journal Entry',
        related='statement_line_id.move_id', store=True, readonly=True,
        help='Accounting journal entry created when this transaction was injected.',
    )

    mapped_account_display = fields.Char(
        string='GL Account (preview)',
        compute='_compute_mapped_account_display',
        help='Counterpart account this transaction will post to when injected.',
    )

    @api.depends('transaction_type', 'accounting_subtype')
    def _compute_mapped_account_display(self):
        settings = self.env['usa.settings'].sudo().search([], limit=1)
        for rec in self:
            account = False
            try:
                if settings:
                    account = settings._get_account_for_transaction(rec)
            except Exception:
                account = False
            rec.mapped_account_display = (
                '%s %s' % (account.code, account.name) if account
                else _('Suspense / unmapped')
            )

    injection_mode = fields.Char(
        string='Injection Mode',
        compute='_compute_injection_mode',
        help='Posting mode resolved from the mapping rules: '
             'gl / customer_invoice / vendor_bill.',
    )

    @api.depends('transaction_type', 'accounting_subtype')
    def _compute_injection_mode(self):
        settings = self.env['usa.settings'].sudo().search([], limit=1)
        for rec in self:
            try:
                rec.injection_mode = (
                    settings._get_posting_mode_for_transaction(rec)
                    if settings else 'gl')
            except Exception:
                rec.injection_mode = 'gl'

    def action_view_journal_entry(self):
        """Open the accounting journal entry this transaction was injected into."""
        self.ensure_one()
        if not self.move_id:
            raise UserError(_('This transaction has not been injected into accounting yet.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Journal Entry'),
            'res_model': 'account.move',
            'res_id': self.move_id.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
        }

    def _find_partner_for_transaction(self):
        """Best-effort partner matching for a single Upwork transaction."""
        self.ensure_one()
        Partner = self.env['res.partner']

        # Search by client company name
        if self.assignment_company_name:
            partner = Partner.search(
                [('name', 'ilike', self.assignment_company_name),
                 ('is_company', '=', True)],
                limit=1,
            )
            if partner:
                return partner

        return Partner

    def _get_accounting_date(self):
        """Date used for Odoo accounting postings (the injected bank line and the
        customer invoice / vendor bill / credit note).

        Upwork's ledger "Date" is the **review-due (availability) date** — when the
        transaction posts to the Upwork balance after the review/security hold — not
        the creation date (which is ~5 days earlier, the earnings period-end). We post
        on review_due_date so Odoo lines up with the Upwork statement, falling back to
        creation_date, then today."""
        self.ensure_one()
        dt = self.transaction_review_due_date or self.transaction_creation_date
        return dt.date() if dt else fields.Date.context_today(self)

    def action_inject_to_accounting(self):
        """Create account.bank.statement.line records from selected Upwork transactions."""
        settings = self.env['usa.settings'].sudo()._get_singleton()
        journal = settings.journal_id
        if not journal:
            raise UserError(_(
                'No bank journal configured for Upwork. '
                'Go to Configuration → Mapping to Odoo Accounting and select a journal.'
            ))

        StatementLine = self.env['account.bank.statement.line']
        journal_currency = journal.currency_id or journal.company_id.currency_id

        injected = 0
        skipped = 0
        unmapped = 0
        doc_suspense = 0
        errors = []

        for rec in self:
            # Skip already injected
            if rec.statement_line_id:
                skipped += 1
                continue

            # Skip zero-amount
            if not rec.transaction_amount_raw and not rec.amount_credited_raw:
                skipped += 1
                continue

            # Dedup check — another usa.transaction with same upwork_tx_ref already linked
            dup = self.search([
                ('upwork_tx_ref', '=', rec.upwork_tx_ref),
                ('statement_line_id', '!=', False),
                ('id', '!=', rec.id),
            ], limit=1)
            if dup and dup.statement_line_id:
                rec.statement_line_id = dup.statement_line_id.id
                skipped += 1
                continue

            # Partner matching
            partner = rec._find_partner_for_transaction()

            # Payment reference
            payment_ref = rec.description_ui or rec.description or rec.record_id

            # Date — Upwork's ledger date is the review-due date, not creation date.
            tx_date = rec._get_accounting_date()

            # Multi-currency handling
            tx_currency = self.env['res.currency'].search(
                [('name', '=', (rec.transaction_amount_currency or '').upper())],
                limit=1,
            )

            # Use amount_credited_raw — it carries the correct sign
            # (positive for money in, negative for fees/withdrawals)
            amount = rec.amount_credited_raw or rec.transaction_amount_raw

            # Resolve mapping: counterpart GL account + posting mode
            counterpart_account = settings._get_account_for_transaction(rec)
            mode = settings._get_posting_mode_for_transaction(rec)
            if mode != 'gl':
                doc_suspense += 1
            elif not counterpart_account:
                unmapped += 1

            vals = {
                'date': tx_date,
                'journal_id': journal.id,
                'payment_ref': payment_ref,
                'amount': amount,
                'upwork_tx_ref': rec.upwork_tx_ref,
            }

            # Direct-GL mode posts the counterpart to the mapped account via the
            # account.bank.statement.line.create() magic key. Document modes
            # (customer_invoice / vendor_bill) intentionally leave the line in
            # suspense so the generated invoice/bill can be reconciled against it.
            if mode == 'gl' and counterpart_account:
                vals['counterpart_account_id'] = counterpart_account.id

            if partner:
                vals['partner_id'] = partner.id

            # Set foreign currency only when amount is non-zero and currencies differ
            if tx_currency and tx_currency != journal_currency and amount:
                vals['foreign_currency_id'] = tx_currency.id
                vals['amount_currency'] = amount

            try:
                line = StatementLine.create(vals)
                rec.statement_line_id = line.id
                injected += 1
            except Exception as e:
                errors.append(f'{rec.record_id}: {str(e)[:100]}')

        # Result notification
        total = len(self)
        msg_parts = [f'{injected}/{total} transactions injected to accounting.']
        if skipped:
            msg_parts.append(f'{skipped} skipped (already injected or zero amount).')
        if doc_suspense:
            msg_parts.append(
                f'{doc_suspense} held in suspense for invoice/bill reconciliation '
                f'(document mode).')
        if unmapped:
            msg_parts.append(
                f'{unmapped} had no mapping rule (posted to the journal suspense '
                f'account) — add rules in Configuration → Mapping to Odoo Accounting.')
        if errors:
            msg_parts.append(f'{len(errors)} errors: ' + '; '.join(errors[:3]))
            if len(errors) > 3:
                msg_parts.append(f'... and {len(errors) - 3} more.')

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Inject to Accounting'),
                'message': ' '.join(msg_parts),
                'type': 'success' if injected and not errors else ('warning' if errors else 'info'),
                'sticky': bool(errors),
            },
        }

    # Document links created from a transaction — removed together with the bank line
    _ACCOUNTING_DOC_FIELDS = (
        'vendor_bill_id', 'customer_invoice_id',
        'customer_refund_id', 'vendor_refund_id',
    )

    def _remove_document_move(self, move, warnings=None):
        """Unreconcile, reset to draft and delete a document move (bill / invoice /
        credit note). Returns True on success."""
        self.ensure_one()
        move = move.sudo()
        try:
            for ml in move.line_ids:
                (ml.matched_debit_ids + ml.matched_credit_ids).sudo().unlink()
            if move.state == 'posted':
                move.button_draft()
            move.unlink()
            return True
        except Exception as e:
            if warnings is not None:
                warnings.append(f'{self.record_id}: Could not remove document — {str(e)[:80]}')
            _logger.warning("Could not remove document move %s: %s", move.id, e)
            return False

    def action_remove_from_accounting(self):
        """Full undo: delete the injected bank statement line AND every accounting
        document created from the transaction (vendor bill, customer invoice,
        customer/vendor credit notes), so the transaction can be re-processed cleanly."""
        removed_lines = 0
        removed_docs = 0
        warnings = []

        for rec in self:
            # 1. Remove any documents created from this transaction
            for fname in self._ACCOUNTING_DOC_FIELDS:
                doc = rec[fname]
                if doc and rec._remove_document_move(doc, warnings):
                    removed_docs += 1
                    rec.sudo().write({fname: False})

            # 2. Remove the injected bank statement line
            if not rec.statement_line_id:
                continue
            line = rec.sudo().statement_line_id
            move = line.move_id

            if line.is_reconciled:
                try:
                    for ml in move.line_ids:
                        (ml.matched_debit_ids + ml.matched_credit_ids).sudo().unlink()
                except Exception as e:
                    warnings.append(
                        f'{rec.record_id}: Could not unreconcile — {str(e)[:80]}')
                    continue

            rec.sudo().write({'statement_line_id': False})
            try:
                if move.state == 'posted':
                    move.sudo().button_draft()
                move.sudo().unlink()
                removed_lines += 1
            except Exception as e:
                warnings.append(
                    f'{rec.record_id}: Could not delete — {str(e)[:80]}')

        msg_parts = [
            f'{removed_lines} statement line(s) and {removed_docs} document(s) removed.']
        if warnings:
            msg_parts.append(' | '.join(warnings[:3]))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Remove from Accounting'),
                'message': ' '.join(msg_parts),
                'type': 'success' if (removed_lines or removed_docs) and not warnings else 'warning',
                'sticky': bool(warnings),
            },
        }

import logging

import openai

from odoo import api, fields, models, Command, _
from odoo.exceptions import UserError

from .openai_prompts import (
    InvoiceExtraction,
    INVOICE_EXTRACTION_PROMPT,
)

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = 'account.move'

    ai_extract_state = fields.Selection(
        selection=[
            ('no_extract', 'No extraction requested'),
            ('extracting', 'Extracting...'),
            ('done', 'Extraction complete'),
            ('error', 'Extraction failed'),
        ],
        string='AI Extraction State',
        default='no_extract',
        copy=False,
        required=True,
    )
    ai_extract_error = fields.Char(
        string='AI Extraction Error',
        copy=False,
    )
    ai_extract_can_show_send_button = fields.Boolean(
        string='Can show AI extract button',
        compute='_compute_ai_extract_can_show_send_button',
    )

    @api.depends('ai_extract_state', 'state', 'move_type', 'message_main_attachment_id')
    def _compute_ai_extract_can_show_send_button(self):
        for move in self:
            move.ai_extract_can_show_send_button = (
                move.state == 'draft'
                and move.is_purchase_document()
                and move.message_main_attachment_id
                and move.ai_extract_state in ('no_extract', 'error')
                and move.company_id.ai_invoice_extract_mode != 'no_send'
            )

    # ── Public actions ──────────────────────────────────────────────

    def action_ai_extract(self):
        """Manual trigger: 'Extract with AI' button."""
        self.ensure_one()
        self._ai_extract_invoice_data()

    def action_ai_extract_retry(self):
        """Retry after error."""
        self.ensure_one()
        self.ai_extract_state = 'no_extract'
        self.ai_extract_error = False
        self._ai_extract_invoice_data()

    # ── Core extraction ─────────────────────────────────────────────

    def _ai_extract_invoice_data(self):
        """Send the main attachment to OpenAI and populate invoice fields."""
        self.ensure_one()
        attachment = self.message_main_attachment_id
        if not attachment or not attachment.datas:
            return

        company = self.company_id
        api_key = (company.openai_api_key or '').strip()
        model_name = (company.openai_model or 'gpt-4o').strip()

        if not api_key:
            self.ai_extract_state = 'error'
            self.ai_extract_error = _("OpenAI API Key is not configured. Go to Settings > Accounting.")
            return

        self.ai_extract_state = 'extracting'
        self.ai_extract_error = False
        # Flush state so the UI can show the banner immediately
        self.env.cr.commit()

        try:
            client = openai.OpenAI(api_key=api_key)

            base64_string = attachment.datas.decode('utf-8')
            file_data_uri = f"data:{attachment.mimetype};base64,{base64_string}"

            input_messages = [
                {"role": "system", "content": INVOICE_EXTRACTION_PROMPT},
                {"role": "user", "content": [
                    {
                        "type": "input_file",
                        "filename": attachment.name or "invoice.pdf",
                        "file_data": file_data_uri,
                    },
                    {
                        "type": "input_text",
                        "text": "Extract all data from this invoice.",
                    },
                ]},
            ]

            _logger.info(
                "AI Invoice Extract: calling OpenAI model '%s' for move %s (attachment: %s)",
                model_name, self.id, attachment.name,
            )

            response = client.responses.parse(
                model=model_name,
                input=input_messages,
                text_format=InvoiceExtraction,
            )

            # Extract parsed result
            result = None
            if hasattr(response, 'output_parsed'):
                result = response.output_parsed
            elif hasattr(response, 'parsed'):
                result = response.parsed

            if not result:
                self.ai_extract_state = 'error'
                self.ai_extract_error = _("OpenAI returned an empty or unparseable response.")
                return

            self._ai_populate_invoice(result)
            self.ai_extract_state = 'done'
            _logger.info("AI Invoice Extract: successfully populated move %s", self.id)

        except openai.AuthenticationError:
            self.ai_extract_state = 'error'
            self.ai_extract_error = _("Invalid OpenAI API key. Check Settings > Accounting.")
        except openai.RateLimitError:
            self.ai_extract_state = 'error'
            self.ai_extract_error = _("OpenAI rate limit exceeded. Please retry later.")
        except openai.APIError as e:
            self.ai_extract_state = 'error'
            self.ai_extract_error = _("OpenAI API error: %s", str(e)[:200])
            _logger.exception("AI Invoice Extract: API error for move %s", self.id)
        except Exception as e:
            self.ai_extract_state = 'error'
            self.ai_extract_error = _("Extraction failed: %s", str(e)[:200])
            _logger.exception("AI Invoice Extract: unexpected error for move %s", self.id)

    # ── Field population ────────────────────────────────────────────

    def _ai_populate_invoice(self, data):
        """Populate invoice fields from the extraction result."""
        self.ensure_one()

        vals = {}

        # Partner
        if not self.partner_id and (data.vendor_vat or data.vendor_name):
            partner = self._ai_match_partner(data.vendor_name, data.vendor_vat)
            if partner:
                vals['partner_id'] = partner.id

        # Reference
        if data.invoice_number and not self.ref:
            vals['ref'] = data.invoice_number

        # Dates
        if data.invoice_date and not self.invoice_date:
            try:
                vals['invoice_date'] = fields.Date.to_date(data.invoice_date)
            except (ValueError, TypeError):
                pass

        if data.due_date and not self.invoice_date_due:
            try:
                vals['invoice_date_due'] = fields.Date.to_date(data.due_date)
            except (ValueError, TypeError):
                pass

        # Payment reference
        if data.payment_reference and not self.payment_reference:
            vals['payment_reference'] = data.payment_reference

        # Currency
        if data.currency and self.currency_id == self.company_currency_id:
            currency = self._ai_match_currency(data.currency)
            if currency:
                vals['currency_id'] = currency.id

        # Apply header fields first
        if vals:
            self.write(vals)

        # Invoice lines (only if no lines exist yet)
        if data.lines and not self.invoice_line_ids:
            self._ai_create_invoice_lines(data.lines)

    def _ai_create_invoice_lines(self, lines):
        """Create invoice lines from extracted data."""
        line_commands = []
        for line_data in lines:
            line_vals = {
                'name': line_data.description or '/',
                'quantity': line_data.quantity or 1.0,
                'price_unit': line_data.unit_price or 0.0,
            }

            # Match tax
            if line_data.tax_percent is not None:
                tax = self._ai_match_tax(line_data.tax_percent)
                if tax:
                    line_vals['tax_ids'] = [Command.set(tax.ids)]

            line_commands.append(Command.create(line_vals))

        if line_commands:
            self.write({'invoice_line_ids': line_commands})

    # ── Matching helpers ────────────────────────────────────────────

    def _ai_match_partner(self, vendor_name, vendor_vat):
        """Find or match a partner by VAT (priority) or name."""
        Partner = self.env['res.partner']

        # Priority 1: Match by VAT
        if vendor_vat:
            vat_clean = vendor_vat.strip().upper()
            partner = Partner.search([
                ('vat', '=ilike', vat_clean),
                ('company_id', 'in', [self.company_id.id, False]),
            ], limit=1)
            if partner:
                return partner

            # Try without country prefix
            if len(vat_clean) > 2 and vat_clean[:2].isalpha():
                vat_number_only = vat_clean[2:]
                partner = Partner.search([
                    ('vat', 'ilike', vat_number_only),
                    ('company_id', 'in', [self.company_id.id, False]),
                ], limit=1)
                if partner:
                    return partner

        # Priority 2: Match by name
        if vendor_name:
            name_clean = vendor_name.strip()
            # Exact match first
            partner = Partner.search([
                ('name', '=ilike', name_clean),
                ('is_company', '=', True),
                ('company_id', 'in', [self.company_id.id, False]),
            ], limit=1)
            if partner:
                return partner

            # Fuzzy: contains match
            partner = Partner.search([
                ('name', 'ilike', name_clean),
                ('is_company', '=', True),
                ('company_id', 'in', [self.company_id.id, False]),
            ], limit=1)
            if partner:
                return partner

        return False

    def _ai_match_tax(self, tax_percent):
        """Find a purchase tax matching the given percentage."""
        if tax_percent is None:
            return False

        taxes = self.env['account.tax'].search([
            ('amount', '=', tax_percent),
            ('amount_type', '=', 'percent'),
            ('type_tax_use', '=', 'purchase'),
            ('company_id', '=', self.company_id.id),
        ], limit=1)

        if not taxes:
            # Try with rounding tolerance
            all_purchase_taxes = self.env['account.tax'].search([
                ('amount_type', '=', 'percent'),
                ('type_tax_use', '=', 'purchase'),
                ('company_id', '=', self.company_id.id),
            ])
            for tax in all_purchase_taxes:
                if abs(tax.amount - tax_percent) < 0.01:
                    return tax

        return taxes

    def _ai_match_currency(self, currency_code):
        """Find a currency by ISO code, name, or symbol."""
        if not currency_code:
            return False

        currency = self.env['res.currency'].search([
            ('name', '=ilike', currency_code.strip()),
            ('active', '=', True),
        ], limit=1)

        if not currency:
            currency = self.env['res.currency'].search([
                '|',
                ('symbol', '=ilike', currency_code.strip()),
                ('currency_unit_label', '=ilike', currency_code.strip()),
            ], limit=1)

        return currency

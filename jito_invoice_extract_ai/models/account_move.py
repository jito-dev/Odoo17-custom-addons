import logging
import re

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

            # Images use image_url content type; PDFs use input_file
            mimetype = attachment.mimetype or ''
            if mimetype.startswith('image/'):
                file_content = {
                    "type": "input_image",
                    "image_url": file_data_uri,
                }
            else:
                file_content = {
                    "type": "input_file",
                    "filename": attachment.name or "invoice.pdf",
                    "file_data": file_data_uri,
                }

            input_messages = [
                {"role": "system", "content": INVOICE_EXTRACTION_PROMPT},
                {"role": "user", "content": [
                    file_content,
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

        # Extract vendor name/vat from new nested structure
        vendor_name = data.vendor.name if data.vendor else None
        vendor_vat = data.vendor.vat if data.vendor else None

        vals = {}

        # Partner — match existing or create new vendor
        if not self.partner_id and (vendor_vat or vendor_name):
            partner = self._ai_match_partner(vendor_name, vendor_vat)
            if not partner and vendor_name:
                partner = self._ai_create_vendor_partner(vendor_name, vendor_vat)
            if partner:
                vals['partner_id'] = partner.id

        # Reference — AI-extracted invoice number is authoritative, always overwrite
        if data.invoice_number:
            vals['ref'] = data.invoice_number

        # Dates — AI-extracted dates are authoritative, always overwrite
        # (Odoo may auto-compute dates from payment terms when partner is set)
        if data.invoice_date:
            try:
                vals['invoice_date'] = fields.Date.to_date(data.invoice_date)
            except (ValueError, TypeError):
                pass

        if data.due_date:
            try:
                vals['invoice_date_due'] = fields.Date.to_date(data.due_date)
            except (ValueError, TypeError):
                pass

        # Payment reference — AI-extracted is authoritative, always overwrite
        if data.payment_reference:
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

        # Enrich the partner with extracted vendor details
        if self.partner_id and data.vendor:
            self._ai_enrich_partner(self.partner_id, data.vendor)

            # Set the recipient bank on the bill to match the invoice's IBAN
            if data.vendor.bank_accounts and self.is_purchase_document():
                self._ai_set_partner_bank(self.partner_id, data.vendor.bank_accounts)

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

    # ── Partner enrichment ───────────────────────────────────────────

    def _ai_enrich_partner(self, partner, vendor_data):
        """Populate empty fields on the partner from AI-extracted vendor data.

        Only sets fields that are currently empty — never overwrites existing data.
        """
        vals = {}

        # Simple text fields — only set if partner field is empty
        field_map = {
            'street': vendor_data.street,
            'street2': vendor_data.street2,
            'city': vendor_data.city,
            'zip': vendor_data.zip_code,
            'email': vendor_data.email,
            'phone': vendor_data.phone,
            'mobile': vendor_data.mobile,
            'website': vendor_data.website,
        }
        for field_name, value in field_map.items():
            if value and not partner[field_name]:
                vals[field_name] = value.strip()

        # VAT
        if vendor_data.vat and not partner.vat:
            vals['vat'] = vendor_data.vat.strip().upper()

        # Country
        if vendor_data.country and not partner.country_id:
            country = self._ai_match_country(vendor_data.country)
            if country:
                vals['country_id'] = country.id

        # State (requires country)
        if vendor_data.state:
            country_id = vals.get('country_id') or (partner.country_id.id if partner.country_id else False)
            if country_id and not partner.state_id:
                state = self._ai_match_state(vendor_data.state, country_id)
                if state:
                    vals['state_id'] = state.id

        if vals:
            partner.write(vals)
            _logger.info(
                "AI Invoice Extract: enriched partner %s (%s) with fields: %s",
                partner.id, partner.name, ', '.join(vals.keys()),
            )

        # Bank accounts
        if vendor_data.bank_accounts:
            self._ai_create_bank_accounts(partner, vendor_data.bank_accounts)

    def _ai_create_bank_accounts(self, partner, bank_accounts):
        """Create bank accounts on the partner from AI-extracted data.

        Skips duplicates by checking sanitized account number.
        """
        PartnerBank = self.env['res.partner.bank']

        for bank_data in bank_accounts:
            acc_number = bank_data.iban
            if not acc_number:
                continue

            acc_number = acc_number.strip().replace(' ', '')

            # Dedup: check if this account already exists for this partner
            sanitized = re.sub(r'\W+', '', acc_number).upper()
            existing = PartnerBank.search([
                ('sanitized_acc_number', '=', sanitized),
                ('partner_id', '=', partner.id),
            ], limit=1)
            if existing:
                continue

            bank_vals = {
                'acc_number': acc_number,
                'partner_id': partner.id,
            }

            # Match bank by BIC/SWIFT
            if bank_data.bic_swift:
                bic = bank_data.bic_swift.strip().upper()
                bank = self.env['res.bank'].search([
                    ('bic', '=ilike', bic),
                ], limit=1)
                if not bank and bank_data.bank_name:
                    # Try by name
                    bank = self.env['res.bank'].search([
                        ('name', 'ilike', bank_data.bank_name.strip()),
                    ], limit=1)
                if bank:
                    bank_vals['bank_id'] = bank.id

            try:
                PartnerBank.create(bank_vals)
                _logger.info(
                    "AI Invoice Extract: created bank account %s for partner %s (%s)",
                    acc_number, partner.id, partner.name,
                )
            except Exception as e:
                _logger.warning(
                    "AI Invoice Extract: failed to create bank account %s for partner %s: %s",
                    acc_number, partner.id, e,
                )

    def _ai_set_partner_bank(self, partner, bank_accounts):
        """Set partner_bank_id on this bill to the bank account matching the invoice IBAN."""
        PartnerBank = self.env['res.partner.bank']

        for bank_data in bank_accounts:
            if not bank_data.iban:
                continue

            sanitized = re.sub(r'\W+', '', bank_data.iban).upper()

            # Find matching bank account on the partner
            bank_account = PartnerBank.search([
                ('sanitized_acc_number', '=', sanitized),
                ('partner_id', '=', partner.id),
            ], limit=1)

            if bank_account:
                self.partner_bank_id = bank_account
                _logger.info(
                    "AI Invoice Extract: set recipient bank %s on move %s",
                    bank_account.acc_number, self.id,
                )
                return

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

    def _ai_create_vendor_partner(self, vendor_name, vendor_vat):
        """Create a new vendor partner from AI-extracted data."""
        Partner = self.env['res.partner']

        vals = {
            'name': vendor_name.strip(),
            'is_company': True,
            'supplier_rank': 1,
            'company_id': self.company_id.id,
        }
        if vendor_vat:
            vals['vat'] = vendor_vat.strip().upper()

        partner = Partner.create(vals)
        _logger.info(
            "AI Invoice Extract: created new vendor partner %s (%s) for move %s",
            partner.id, partner.name, self.id,
        )
        return partner

    def _ai_match_country(self, country_str):
        """Find a country by ISO code or name."""
        if not country_str:
            return False

        country_str = country_str.strip()
        Country = self.env['res.country']

        # Try as ISO 2-letter code first
        if len(country_str) == 2:
            country = Country.search([
                ('code', '=', country_str.upper()),
            ], limit=1)
            if country:
                return country

        # Try by name (exact, case-insensitive)
        country = Country.search([
            ('name', '=ilike', country_str),
        ], limit=1)
        if country:
            return country

        # Try by name (contains)
        country = Country.search([
            ('name', 'ilike', country_str),
        ], limit=1)
        return country or False

    def _ai_match_state(self, state_str, country_id):
        """Find a state/province within a country by name or code."""
        if not state_str or not country_id:
            return False

        state_str = state_str.strip()
        State = self.env['res.country.state']

        # By code
        state = State.search([
            ('country_id', '=', country_id),
            ('code', '=ilike', state_str),
        ], limit=1)
        if state:
            return state

        # By name (exact)
        state = State.search([
            ('country_id', '=', country_id),
            ('name', '=ilike', state_str),
        ], limit=1)
        if state:
            return state

        # By name (contains)
        state = State.search([
            ('country_id', '=', country_id),
            ('name', 'ilike', state_str),
        ], limit=1)
        return state or False

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

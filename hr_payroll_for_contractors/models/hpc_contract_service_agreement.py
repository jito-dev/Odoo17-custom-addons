import base64
import json
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class HpcContractServiceAgreement(models.Model):
    """Individual service agreement instance between the company and a contractor.
    Based on an hpc.service.agreement template; stores the specific terms,
    parties and state for one contractor contract."""

    _name = 'hpc.contract.service.agreement'
    _description = 'Service Agreement'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name desc'
    # active enables archiving — avoids FK issues when records are in use
    active = fields.Boolean(default=True)

    name = fields.Char(
        string='Reference',
        readonly=True,
        copy=False,
        default=lambda self: _('New'),
    )
    is_templated = fields.Boolean(
        string='Use Agreement Template',
        default=True,
        tracking=True,
        help="When off, this is a one-time service agreement with no template "
             "and no auto-generated documents. Attach signed documents "
             "manually in the 'Signed Documents' tab.",
    )
    template_id = fields.Many2one(
        'hpc.service.agreement',
        string='Agreement Template',
        ondelete='restrict',
        tracking=True,
    )
    contract_id = fields.Many2one(
        'hr.payroll.contractor.contract',
        string='Contract',
        ondelete='set null',
        index=True,
        tracking=True,
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        related='contract_id.employee_id',
        store=True,
        index=True,
    )

    # ── Parties ──────────────────────────────────────────────────────────────

    legal_entity_id = fields.Many2one(
        'hpc.contractor.legal.entity',
        string='Legal Entity',
        ondelete='set null',
        domain="[('contractor_id.employee_id', '=', employee_id)]",
        tracking=True,
    )
    payment_method_id = fields.Many2one(
        'hpc.contractor.payment.method',
        string='Payment Method',
        ondelete='set null',
        domain="[('contractor_id.employee_id', '=', employee_id)]",
        tracking=True,
    )

    # ── State & Dates ─────────────────────────────────────────────────────────

    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('active', 'Active'),
            ('terminated', 'Terminated'),
        ],
        string='Status',
        default='draft',
        tracking=True,
    )
    date_signed = fields.Date(string='Signature Date', tracking=True)
    date_effective = fields.Date(string='Agreement Becomes Effective On', tracking=True)
    date_termination_signed = fields.Date(string='Signature Date', tracking=True)
    date_termination = fields.Date(string='Agreement Fully Terminated On', tracking=True)

    # ── Financial & Contract Terms ────────────────────────────────────────────
    # Defaulted from the template but fully editable per agreement.

    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        tracking=True,
    )
    hourly_rate = fields.Float(
        string='Hourly Rate',
        digits=(12, 2),
        tracking=True,
    )
    termination_notice_days = fields.Integer(
        string='Termination Notice (days)',
        tracking=True,
        help='Number of days either party must give notice before terminating.',
    )
    payment_banking_days = fields.Integer(
        string='Payment Period (banking days)',
        tracking=True,
        help='Number of banking days the customer has to pay the invoice.',
    )
    customer_email_contact_id = fields.Many2one(
        'res.partner',
        string='Customer Official Email Contact',
        tracking=True,
        help='Contact to receive official notices (invoices, termination etc.).',
    )

    # ── Generated Documents ───────────────────────────────────────────────────

    context_data = fields.Text(string='Built Context (JSON)', readonly=True)
    rendered_vars_html = fields.Html(
        string='Template Variables',
        sanitize=False,
        readonly=True,
    )

    # Agreement (initiation)
    agreement_docx_id = fields.Many2one(
        'ir.attachment', string='Agreement DOCX', ondelete='set null', copy=False)
    agreement_pdf_id = fields.Many2one(
        'ir.attachment', string='Agreement PDF', ondelete='set null', copy=False)
    agreement_sign_template_id = fields.Many2one(
        'sign.template', string='Agreement Sign Template', ondelete='set null', copy=False)
    agreement_sign_request_id = fields.Many2one(
        'sign.request', string='Agreement Sign Request',
        compute='_compute_agreement_sign_request', store=False)
    agreement_sign_request_state = fields.Char(
        string='Agreement Signing Status',
        compute='_compute_agreement_sign_request', store=False)

    # Termination
    termination_docx_id = fields.Many2one(
        'ir.attachment', string='Termination DOCX', ondelete='set null', copy=False)
    termination_pdf_id = fields.Many2one(
        'ir.attachment', string='Termination PDF', ondelete='set null', copy=False)
    termination_sign_template_id = fields.Many2one(
        'sign.template', string='Termination Sign Template', ondelete='set null', copy=False)
    termination_sign_request_id = fields.Many2one(
        'sign.request', string='Termination Sign Request',
        compute='_compute_termination_sign_request', store=False)
    termination_sign_request_state = fields.Char(
        string='Termination Signing Status',
        compute='_compute_termination_sign_request', store=False)

    # ── Manually-attached Sign documents ─────────────────────────────────────
    # Already-signed sign.request records (NDAs, addenda, or — for one-time
    # agreements — the agreement itself). Independent of the template-driven
    # *_sign_template_id flow above; can coexist with it.

    signed_sign_request_ids = fields.Many2many(
        'sign.request',
        'hpc_contract_sa_signed_sign_request_rel',
        'sa_id',
        'sign_request_id',
        string='Signed Documents',
        domain="[('state', '=', 'signed')]",
        help='Already-signed Sign module documents attached to this service '
             'agreement (NDAs, addenda, or the full agreement when no '
             'template is used).',
    )

    # ── Vendor ─────────────────────────────────────────────────────────────────

    vendor_id = fields.Many2one(
        'res.partner',
        string='Vendor',
        copy=False,
        help='Vendor partner created from this service agreement data.',
    )

    # ── Notes ─────────────────────────────────────────────────────────────────

    notes = fields.Html(string='Internal Notes', sanitize=True)

    # ── Computed sign request fields ──────────────────────────────────────────

    @api.depends('agreement_sign_template_id')
    def _compute_agreement_sign_request(self):
        for rec in self:
            req = (
                rec.agreement_sign_template_id.sign_request_ids.sorted('id', reverse=True)[:1]
                if rec.agreement_sign_template_id
                else self.env['sign.request'].browse()
            )
            rec.agreement_sign_request_id = req
            rec.agreement_sign_request_state = req.state if req else False

    @api.depends('termination_sign_template_id')
    def _compute_termination_sign_request(self):
        for rec in self:
            req = (
                rec.termination_sign_template_id.sign_request_ids.sorted('id', reverse=True)[:1]
                if rec.termination_sign_template_id
                else self.env['sign.request'].browse()
            )
            rec.termination_sign_request_id = req
            rec.termination_sign_request_state = req.state if req else False

    # ── Sign request reset (teardown) ─────────────────────────────────────────

    def _reset_signing_chain(self, doc_type):
        """Cancel and fully delete the signing chain for the given doc_type
        ('agreement' or 'termination'), then clear the sign_template_id field.

        Teardown order:
          1. Cancel all linked sign.requests (marks as canceled, notifies no-one)
          2. Collect completed-document attachments (won't auto-delete)
          3. Unlink sign.requests  → has_sign_requests becomes False on template
          4. Unlink sign.template  → now safe since no requests remain
          5. Unlink completed-document attachments
          6. Clear *_sign_template_id on this record
        """
        self.ensure_one()
        tpl = self['%s_sign_template_id' % doc_type]
        if not tpl:
            return

        requests = tpl.sudo().sign_request_ids
        completed_atts = requests.mapped('completed_document_attachment_ids')

        # Step 1 — cancel (updates state, prevents new signatures, no email)
        requests.sudo().cancel()
        # Step 2+3 — unlink requests (M2M rows removed, attachments kept)
        requests.sudo().unlink()
        # Step 4 — template is now deletable
        tpl.sudo().unlink()
        # Step 5 — orphaned completed-document attachments
        completed_atts.sudo().unlink()
        # Step 6 — clear our pointer
        self['%s_sign_template_id' % doc_type] = False

    def action_reset_agreement_signing(self):
        self.ensure_one()
        self._reset_signing_chain('agreement')

    def action_reset_termination_signing(self):
        self.ensure_one()
        self._reset_signing_chain('termination')

    # ── Sign request view / download helpers ─────────────────────────────────

    def action_view_agreement_signing(self):
        self.ensure_one()
        req = self.agreement_sign_request_id
        if not req:
            raise UserError(_('No signing request found for the Agreement.'))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sign.request',
            'res_id': req.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_download_agreement_signed(self):
        self.ensure_one()
        req = self.agreement_sign_request_id
        if not req or req.state != 'signed':
            raise UserError(_('Agreement is not fully signed yet.'))
        att = req.completed_document_attachment_ids[:1]
        if not att:
            raise UserError(_('Signed document not found on the signing request.'))
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%d?download=true' % att.id,
            'target': 'self',
        }

    def action_view_termination_signing(self):
        self.ensure_one()
        req = self.termination_sign_request_id
        if not req:
            raise UserError(_('No signing request found for the Termination.'))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sign.request',
            'res_id': req.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_download_termination_signed(self):
        self.ensure_one()
        req = self.termination_sign_request_id
        if not req or req.state != 'signed':
            raise UserError(_('Termination is not fully signed yet.'))
        att = req.completed_document_attachment_ids[:1]
        if not att:
            raise UserError(_('Signed document not found on the signing request.'))
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%d?download=true' % att.id,
            'target': 'self',
        }

    # ── Document generation ───────────────────────────────────────────────────

    def _build_context(self):
        """Build Jinja2 context from SA fields (mirrors hpc_contractor_invoice pattern)."""
        self.ensure_one()

        def _d(v):
            return v.strftime('%d.%m.%Y') if v else ''

        def _d_en(v):
            return ('%d %s %d' % (v.day, v.strftime('%B'), v.year)) if v else ''

        entity = self.legal_entity_id
        pm = self.payment_method_id
        company = self.env.company

        ctx_data = {}
        if entity:
            ctx_data = {
                # Names
                'pe_entity_en_first_name': entity.ua_pe_first_name_en or '',
                'pe_entity_en_last_name':  entity.ua_pe_last_name_en or '',
                'pe_entity_ua_first_name': entity.ua_pe_first_name_ua or '',
                'pe_entity_ua_last_name':  entity.ua_pe_last_name_ua or '',
                'pe_entity_ua_by_father':  entity.ua_pe_by_father_ua or '',
                # Sex
                'pe_entity_sex': entity.ua_pe_sex or '',
                # Registered addresses
                'pe_entity_ua_registered_address': entity.ua_pe_address_ua or '',
                'pe_entity_en_registered_address': entity.ua_pe_address_en or '',
                # Legacy address aliases
                'pe_address_ua': entity.ua_pe_address_ua or '',
                'pe_address_en': entity.ua_pe_address_en or '',
                # Tax / PE register
                'pe_vat_itn': entity.ua_vat_itn or '',
                'pe_united_register_extract_record_number': entity.ua_register_extract_number or '',
                'pe_united_register_extract_date_of_issue': _d(entity.ua_register_extract_date),
                # Contract location
                'contract_location_ua': entity.ua_contract_location_ua or '',
                'contract_location_en': entity.ua_contract_location_en or '',
                # Identity document type
                'pe_id_doc_type': entity.ua_id_doc_type or '',
                # ID Card
                'pe_id_card_number':          entity.ua_id_card_number or '',
                'pe_id_card_document_number': entity.ua_id_card_number or '',
                'pe_id_card_record_number':   entity.ua_id_card_record_number or '',
                'pe_id_card_date_of_issue': _d(entity.ua_id_card_date_of_issue),
                'pe_id_card_authority':     entity.ua_id_card_authority or '',
                # Paper Passport
                'pe_paper_passport_series':        entity.ua_passport_series or '',
                'pe_paper_passport_authority':     entity.ua_passport_authority or '',
                'pe_paper_passport_date_of_issue': _d(entity.ua_passport_date_of_issue),
            }

        # Payment method block
        bank_name = iban = bic_swift = ''
        if pm:
            if pm.method_type == 'sepa':
                bank_name, iban, bic_swift = pm.sepa_bank_name or '', pm.sepa_iban or '', pm.sepa_bic or ''
            elif pm.method_type == 'swift':
                bank_name, iban, bic_swift = pm.swift_bank_name or '', pm.swift_account_number or '', pm.swift_bic or ''
            elif pm.method_type == 'gbp':
                bank_name, iban = pm.gbp_bank_name or '', pm.gbp_account_number or ''
            elif pm.method_type == 'ua_bank_card':
                iban = pm.ua_card_number or ''
        ctx_data.update({
            'payment_bank_name':    bank_name,
            'payment_iban':         iban,
            'payment_bic_swift':    bic_swift,
            'payment_method_type':  pm.method_type if pm else '',
        })

        # SA instance terms
        ctx_data.update({
            'contract_id':                self.name or '',
            'contract_conclusion_date':   _d(self.date_signed),
            'sa_reference':               self.name or '',
            'sa_date_signed':             _d(self.date_signed),
            'sa_date_effective':          _d(self.date_effective),
            'sa_date_termination':        _d(self.date_termination),
            'termination_signature_date_ua':  _d(self.date_termination_signed),
            'termination_signature_date_en':  _d_en(self.date_termination_signed),
            'termination_effective_date_ua':  _d(self.date_termination),
            'termination_effective_date_en':  _d_en(self.date_termination),
            'sa_currency':                self.currency_id.name if self.currency_id else '',
            'contract_currency':          self.currency_id.name if self.currency_id else '',
            'sa_hourly_rate':             self.hourly_rate,
            'sa_termination_notice_days':    self.termination_notice_days,
            'contract_termination_notice':   self.termination_notice_days,
            'sa_payment_banking_days':       self.payment_banking_days,
            'pe_cost_per_hour':           self.hourly_rate,
            'pe_currency':                self.currency_id.name if self.currency_id else '',
        })

        # Company (customer) block
        pay_duration = str(company.hpc_pay_duration) if company.hpc_pay_duration else ''
        rep_en = company.hpc_representative_id.name or company.name or ''
        rep_ua = company.hpc_representative_name_ua or rep_en
        p = company.partner_id
        city_zip = ' '.join(filter(None, [p.city, p.zip]))
        addr_en = ', '.join(filter(None, [
            p.street, p.street2, city_zip or None,
            p.state_id.name if p.state_id else None,
            p.country_id.name if p.country_id else None,
        ]))
        rep_user = (
            self.env['res.users'].search(
                [('partner_id', '=', company.hpc_representative_id.id)], limit=1
            ) if company.hpc_representative_id else self.env['res.users'].browse()
        )
        sig_img = rep_user.with_context(bin_size=False).hpc_signature_img if rep_user else None

        ctx = {
            'ctx': ctx_data,
            'customer': {
                'incorporation_number': company.company_registry or '',
                'itn': company.vat or '',
                'signature': {'img': sig_img or None},
                'en': {'entity': {
                    'legal_name':         company.name or '',
                    'registered_address': addr_en,
                    'representative':     rep_en,
                    'signature':          rep_en,
                    'pay_duration':       pay_duration,
                }},
                'ua': {'entity': {
                    'legal_name':         company.hpc_legal_name_ua or company.name or '',
                    'registered_address': addr_en,
                    'representative':     rep_ua,
                    'signature':          rep_ua,
                    'pay_duration':       pay_duration,
                }},
            },
        }
        self.context_data = json.dumps(ctx, default=str, indent=2)
        self.rendered_vars_html = self._build_rendered_vars_html(ctx)
        return ctx

    def _build_rendered_vars_html(self, ctx):
        """Build combined HTML table showing Jinja2 variables resolved from ctx
        for Agreement (Initiation) and Termination template slots."""
        from odoo.addons.jito_document_template.services.docx_renderer import (  # noqa: PLC0415
            extract_jinja_variables, build_rendered_vars_html)

        tpl_rec = self.template_id
        if not tpl_rec:
            return False

        slots = [
            ('Agreement (Initiation) Template', 'init_template_file'),
            ('Termination Template',            'term_template_file'),
        ]
        html_parts = []
        for label, field_name in slots:
            file_b64 = tpl_rec.with_context(bin_size=False)[field_name]
            if not file_b64:
                html_parts.append(
                    '<p class="text-muted small mb-1"><em>%s — no template uploaded.</em></p>'
                    % label
                )
                continue
            try:
                variables = extract_jinja_variables(base64.b64decode(file_b64))
                table = build_rendered_vars_html(variables, ctx)
                html_parts.append('<h6 class="mt-3 mb-1 fw-bold">%s</h6>%s' % (label, table))
            except Exception as e:
                html_parts.append(
                    '<p class="text-danger small">Could not parse %s: %s</p>' % (label, str(e))
                )
        return ''.join(html_parts) or False

    def action_rebuild_context(self):
        """Public action: rebuild context_data + rendered_vars_html from current field values."""
        self.ensure_one()
        self._ensure_templated()
        self._build_context()

    # Map template file field → corresponding output filename field on the template
    _OUTPUT_FILENAME_FIELDS = {
        'init_template_file': 'init_output_filename',
        'term_template_file': 'term_output_filename',
    }

    def _resolve_output_filename(self, template_file_field, ctx, basename, ext):
        """Return the rendered output filename for the given template slot.

        Uses the template's output_filename Jinja2 string when set; falls back
        to '<basename>_<sa-reference>.<ext>'.
        """
        from odoo.addons.jito_document_template.services.docx_renderer import (  # noqa: PLC0415
            render_string)
        out_field = self._OUTPUT_FILENAME_FIELDS.get(template_file_field)
        tpl_str = self.template_id[out_field] if out_field else None
        if tpl_str:
            try:
                name = render_string(tpl_str, ctx).strip()
                if name:
                    # Ensure correct extension regardless of what the template says
                    base = name.rsplit('.', 1)[0] if '.' in name else name
                    return '%s.%s' % (base, ext)
            except Exception:
                pass
        return '%s_%s.%s' % (basename, self.name, ext)

    def _generate_docs(self, template_file_field, basename):
        """Render DOCX (and PDF if LibreOffice available) from a template Binary field."""
        from odoo.addons.jito_document_template.services.docx_renderer import (  # noqa: PLC0415
            render_docx, convert_to_pdf, is_libreoffice_available)

        tpl = self.template_id
        if not tpl:
            raise UserError(_('No agreement template selected.'))
        file_b64 = tpl.with_context(bin_size=False)[template_file_field]
        if not file_b64:
            raise UserError(_('No .docx file uploaded for this document type in the template.'))

        ctx = self._build_context()
        docx_bytes = render_docx(base64.b64decode(file_b64), ctx)
        docx_name = self._resolve_output_filename(template_file_field, ctx, basename, 'docx')

        docx_att = self.env['ir.attachment'].create({
            'name': docx_name,
            'datas': base64.b64encode(docx_bytes),
            'mimetype': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'res_model': self._name,
            'res_id': self.id,
        })

        pdf_att = False
        if is_libreoffice_available():
            try:
                pdf_bytes = convert_to_pdf(docx_bytes)
                pdf_name = self._resolve_output_filename(template_file_field, ctx, basename, 'pdf')
                pdf_att = self.env['ir.attachment'].create({
                    'name': pdf_name,
                    'datas': base64.b64encode(pdf_bytes),
                    'mimetype': 'application/pdf',
                    'res_model': self._name,
                    'res_id': self.id,
                })
            except Exception as e:
                _logger.warning('PDF conversion failed: %s', e)

        return docx_att, pdf_att

    def _ensure_templated(self):
        """Block template-driven actions when the SA is in one-time mode."""
        self.ensure_one()
        if not self.is_templated:
            raise UserError(_(
                'This service agreement is not templated. Enable '
                '"Use Agreement Template" first.'
            ))

    def action_generate_agreement(self):
        self.ensure_one()
        self._ensure_templated()
        docx_att, pdf_att = self._generate_docs('init_template_file', 'agreement')
        self.write({
            'agreement_docx_id': docx_att.id,
            'agreement_pdf_id': pdf_att.id if pdf_att else False,
        })

    def action_generate_termination(self):
        self.ensure_one()
        self._ensure_templated()
        docx_att, pdf_att = self._generate_docs('term_template_file', 'termination')
        self.write({
            'termination_docx_id': docx_att.id,
            'termination_pdf_id': pdf_att.id if pdf_att else False,
        })

    def action_send_agreement_for_signing(self):
        self.ensure_one()
        self._ensure_templated()
        if not self.agreement_pdf_id:
            raise UserError(_('Generate the Agreement PDF first.'))
        sign_tpl = self.env['sign.template'].create({'attachment_id': self.agreement_pdf_id.id})
        self.agreement_sign_template_id = sign_tpl.id
        return {
            'type': 'ir.actions.client',
            'tag': 'sign.Template',
            'params': {'id': sign_tpl.id, 'sign_directly_without_mail': False},
        }

    def action_send_termination_for_signing(self):
        self.ensure_one()
        self._ensure_templated()
        if not self.termination_pdf_id:
            raise UserError(_('Generate the Termination PDF first.'))
        sign_tpl = self.env['sign.template'].create({'attachment_id': self.termination_pdf_id.id})
        self.termination_sign_template_id = sign_tpl.id
        return {
            'type': 'ir.actions.client',
            'tag': 'sign.Template',
            'params': {'id': sign_tpl.id, 'sign_directly_without_mail': False},
        }

    def action_download_agreement_docx(self):
        self.ensure_one()
        if not self.agreement_docx_id:
            raise UserError(_('No Agreement DOCX generated yet.'))
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%d?download=true' % self.agreement_docx_id.id,
            'target': 'self',
        }

    def action_download_agreement_pdf(self):
        self.ensure_one()
        if not self.agreement_pdf_id:
            raise UserError(_('No Agreement PDF generated yet.'))
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%d?download=true' % self.agreement_pdf_id.id,
            'target': 'self',
        }

    def action_download_termination_docx(self):
        self.ensure_one()
        if not self.termination_docx_id:
            raise UserError(_('No Termination DOCX generated yet.'))
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%d?download=true' % self.termination_docx_id.id,
            'target': 'self',
        }

    def action_download_termination_pdf(self):
        self.ensure_one()
        if not self.termination_pdf_id:
            raise UserError(_('No Termination PDF generated yet.'))
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%d?download=true' % self.termination_pdf_id.id,
            'target': 'self',
        }

    # ── Create Vendor ────────────────────────────────────────────────────────

    def action_create_vendor(self):
        """Create a res.partner vendor from the service agreement's legal entity
        and payment method data, and optionally a linked bank account."""
        self.ensure_one()

        if self.vendor_id:
            raise UserError(_('A vendor has already been created for this service agreement.'))
        if not self.legal_entity_id:
            raise UserError(_('Please set a Legal Entity before creating a vendor.'))

        entity = self.legal_entity_id
        employee = self.employee_id
        pm = self.payment_method_id

        # Build partner name from English name fields
        name_parts = list(filter(None, [
            entity.ua_pe_first_name_en,
            entity.ua_pe_last_name_en,
        ]))
        partner_name = ' '.join(name_parts) if name_parts else (
            employee.name if employee else entity.display_name
        )

        # Email and phone from employee
        email = ''
        phone = ''
        if employee:
            email = employee.work_email or employee.private_email or ''
            phone = employee.mobile_phone or employee.work_phone or ''

        partner_vals = {
            'name': partner_name,
            'is_company': entity.entity_type == 'ua_pe',
            'supplier_rank': 1,
            'vat': entity.ua_vat_itn or False,
            'street': entity.ua_pe_addr_street1_en or False,
            'street2': entity.ua_pe_addr_street2_en or False,
            'city': entity.ua_pe_addr_city_en or False,
            'zip': entity.ua_pe_addr_postal_code or False,
            'country_id': entity.ua_pe_addr_country_id.id if entity.ua_pe_addr_country_id else False,
            'email': email or False,
            'phone': phone or False,
        }

        partner = self.env['res.partner'].create(partner_vals)

        # Create bank account if payment method has bank details
        if pm and pm.method_type in ('sepa', 'swift', 'gbp'):
            acc_number = False
            bank_bic = False
            bank_name_val = False

            if pm.method_type == 'sepa':
                acc_number = pm.sepa_iban
                bank_bic = pm.sepa_bic
                bank_name_val = pm.sepa_bank_name
            elif pm.method_type == 'swift':
                acc_number = pm.swift_account_number
                bank_bic = pm.swift_bic
                bank_name_val = pm.swift_bank_name
            elif pm.method_type == 'gbp':
                acc_number = pm.gbp_account_number
                bank_name_val = pm.gbp_bank_name

            if acc_number:
                bank_vals = {
                    'acc_number': acc_number,
                    'partner_id': partner.id,
                    'allow_out_payment': True,
                }
                if bank_bic:
                    bank_vals['bank_bic'] = bank_bic
                if bank_name_val:
                    bank_vals['bank_name'] = bank_name_val
                self.env['res.partner.bank'].create(bank_vals)

        self.vendor_id = partner.id

        # Link to employee's work_contact_id if not already set
        if employee and not employee.work_contact_id:
            employee.work_contact_id = partner.id

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Vendor Created'),
                'message': _('Vendor "%s" has been created successfully.', partner.name),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    # ── ORM ───────────────────────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'hpc.contract.service.agreement'
                ) or _('New')
        records = super().create(vals_list)
        # Auto-link back to the contract if it has no SA yet
        for rec in records:
            if rec.contract_id and not rec.contract_id.service_agreement_id:
                rec.contract_id.service_agreement_id = rec.id
        return records

    # ── Onchange ──────────────────────────────────────────────────────────────

    @api.onchange('contract_id')
    def _onchange_contract_id(self):
        """Pre-fill parties from the linked contract."""
        contract = self.contract_id
        if not contract:
            return
        if not self.legal_entity_id and contract.legal_entity_id:
            self.legal_entity_id = contract.legal_entity_id
        if not self.payment_method_id and contract.payment_method_id:
            self.payment_method_id = contract.payment_method_id

    @api.onchange('is_templated')
    def _onchange_is_templated(self):
        """Clear the template when the SA is flipped to one-time mode so the
        UI doesn't keep a stale selection that's no longer visible."""
        if not self.is_templated:
            self.template_id = False

    @api.constrains('is_templated', 'template_id')
    def _check_template_required(self):
        for rec in self:
            if rec.is_templated and not rec.template_id:
                raise ValidationError(_(
                    "Agreement Template is required when 'Use Agreement "
                    "Template' is enabled."
                ))

    @api.onchange('template_id')
    def _onchange_template_id(self):
        """Pre-fill financial terms from the selected template."""
        tpl = self.template_id
        if not tpl:
            return
        if not self.currency_id:
            self.currency_id = tpl.currency_id
        if not self.hourly_rate:
            self.hourly_rate = tpl.default_hourly_rate
        if not self.termination_notice_days:
            self.termination_notice_days = tpl.termination_notice_days
        if not self.payment_banking_days:
            self.payment_banking_days = tpl.payment_banking_days
        if not self.customer_email_contact_id:
            self.customer_email_contact_id = tpl.customer_email_contact_id

    # ── State transitions ─────────────────────────────────────────────────────

    def action_activate(self):
        self.write({'state': 'active'})

    def action_terminate(self):
        self.write({'state': 'terminated'})

    def action_reset_draft(self):
        self.write({'state': 'draft'})

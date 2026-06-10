import base64
import json
import logging
import random
import string

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class HpcContractorInvoice(models.Model):
    _name = 'hpc.contractor.invoice'
    _description = 'Contractor-issued Invoice'
    _inherit = ['mail.thread']
    _order = 'name desc'

    name = fields.Char(
        string='Reference',
        readonly=True,
        copy=False,
        default=lambda self: _('New'),
    )
    invoice_uid = fields.Char(
        string='Invoice UID',
        readonly=True,
        copy=False,
        help='Unique 6-character alphanumeric identifier for this invoice. '
             'Generated on first context build. Use as {{ ctx.invoice_id }} in templates.',
    )
    salary_run_id = fields.Many2one(
        'hr.payroll.contractor.salary.run',
        string='Salary Run',
        ondelete='cascade',
        index=True,
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        index=True,
        store=True,
    )
    legal_entity_id = fields.Many2one(
        'hpc.contractor.legal.entity',
        string='Legal Entity',
        ondelete='set null',
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('generated', 'Generated'),
        ],
        string='Status',
        default='draft',
        tracking=True,
    )
    hours_on_invoice = fields.Float(
        string='Hours on Invoice',
        readonly=True,
        help='Computed as: Total Amount ÷ Hourly Rate from the linked Service Agreement.',
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='salary_run_id.currency_id',
        store=True,
        readonly=True,
    )
    amount_on_invoice = fields.Monetary(
        string='Amount on Invoice',
        currency_field='currency_id',
        readonly=True,
    )
    context_data = fields.Text(string='Built Context (JSON)', readonly=True)
    rendered_vars_html = fields.Html(
        string='Template Variables',
        sanitize=False,
        readonly=True,
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

    # ── Sign fields ───────────────────────────────────────────────────────────

    invoice_sign_template_id = fields.Many2one(
        'sign.template',
        string='Sign Template',
        ondelete='set null',
        copy=False,
    )
    invoice_sign_request_id = fields.Many2one(
        'sign.request',
        string='Sign Request',
        compute='_compute_invoice_sign_request',
        store=False,
    )
    invoice_sign_request_state = fields.Char(
        string='Signing Status',
        compute='_compute_invoice_sign_request',
        store=False,
    )

    # ── Computed ──────────────────────────────────────────────────────────────

    @api.depends('invoice_sign_template_id')
    def _compute_invoice_sign_request(self):
        for rec in self:
            req = (
                rec.invoice_sign_template_id.sign_request_ids.sorted('id', reverse=True)[:1]
                if rec.invoice_sign_template_id
                else self.env['sign.request'].browse()
            )
            rec.invoice_sign_request_id = req
            rec.invoice_sign_request_state = req.state if req else False

    # ── Onchange ──────────────────────────────────────────────────────────────

    @api.onchange('salary_run_id')
    def _onchange_salary_run_id(self):
        run = self.salary_run_id
        if not run:
            return
        self.employee_id = run.employee_id
        contract = run.contract_id
        if contract and contract.legal_entity_id:
            self.legal_entity_id = contract.legal_entity_id

    # ── Sequence ──────────────────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = (
                    self.env['ir.sequence'].next_by_code('hpc.contractor.invoice')
                    or _('New')
                )
        return super().create(vals_list)

    # ── Context builder ───────────────────────────────────────────────────────

    def action_build_context(self):
        """Build Jinja2 context from salary run data.

        For UA PE Hourly Consulting agreements:
          hours_on_invoice = total_to_pay / sa.hourly_rate
        """
        self.ensure_one()
        run = self.salary_run_id
        if not run:
            raise UserError(_('No salary run linked to this contractor invoice.'))

        entity = self.legal_entity_id
        company = self.env.company
        contract = run.contract_id

        # Resolve service agreement via contract
        sa = contract.service_agreement_id if contract else None

        def _d(date_val):
            return date_val.strftime('%d.%m.%Y') if date_val else ''

        # ── Legal entity block ────────────────────────────────────────────────
        ctx_data = {}
        if entity:
            ctx_data = {
                'contract_location_ua': entity.ua_contract_location_ua or '',
                'contract_location_en': entity.ua_contract_location_en or '',
                'pe_entity_en_first_name': entity.ua_pe_first_name_en or '',
                'pe_entity_en_last_name': entity.ua_pe_last_name_en or '',
                'pe_entity_ua_first_name': entity.ua_pe_first_name_ua or '',
                'pe_entity_ua_last_name': entity.ua_pe_last_name_ua or '',
                'pe_entity_ua_by_father': entity.ua_pe_by_father_ua or '',
                'pe_vat_itn': entity.ua_vat_itn or '',
                'pe_united_register_extract_record_number': entity.ua_register_extract_number or '',
                'pe_united_register_extract_date_of_issue': _d(entity.ua_register_extract_date),
                'pe_entity_ua_registered_address': entity.ua_pe_address_ua or '',
                'pe_entity_en_registered_address': entity.ua_pe_address_en or '',
                'pe_address_ua': entity.ua_pe_address_ua or '',
                'pe_address_en': entity.ua_pe_address_en or '',
            }

        # ── Hours / rate calculation ──────────────────────────────────────────
        amount = run.total_to_pay
        hourly_rate = 0.0
        hours = 0.0

        if sa and sa.template_id:
            tpl = sa.template_id
            if (tpl.agreement_category == 'ua_pe_hourly_consulting'
                    and tpl.agreement_type == 'hourly_based'):
                hourly_rate = sa.hourly_rate or 0.0
                if hourly_rate:
                    hours = round(amount / hourly_rate, 4)

        # ── Payment method (prefer SA → fallback contract) ────────────────────
        pm = None
        if sa and sa.payment_method_id:
            pm = sa.payment_method_id
        elif contract and contract.payment_method_id:
            pm = contract.payment_method_id

        bank_name = iban = bic_swift = ''
        if pm:
            if pm.method_type == 'sepa':
                bank_name = pm.sepa_bank_name or ''
                iban = pm.sepa_iban or ''
                bic_swift = pm.sepa_bic or ''
            elif pm.method_type == 'swift':
                bank_name = pm.swift_bank_name or ''
                iban = pm.swift_account_number or ''
                bic_swift = pm.swift_bic or ''
            elif pm.method_type == 'gbp':
                bank_name = pm.gbp_bank_name or ''
                iban = pm.gbp_account_number or ''
            elif pm.method_type == 'ua_bank_card':
                iban = pm.ua_card_number or ''

        place_en = entity.ua_contract_location_en if entity else ''
        place_ua = entity.ua_contract_location_ua if entity else ''
        invoice_date = _d(run.date_end)
        currency_name = run.currency_id.name if run.currency_id else ''

        # Generate invoice_uid once and persist it
        if not self.invoice_uid:
            chars = string.ascii_uppercase + string.digits
            self.invoice_uid = ''.join(random.choices(chars, k=6))

        ctx_data.update({
            'invoice_id': self.invoice_uid or '',
            'invoice_date': invoice_date,
            'invoice_currency': currency_name,
            'invoice_hours': hours,
            'invoice_cost_per_hour': hourly_rate,
            'invoice_cost_total': amount,
            'invoice_cost_total_per_service': amount,
            'invoice_cost_total_with_vat': amount,
            'invoice_vat': '0',
            'invoice_total_amount': amount,
            'invoice_place_en': place_en,
            'invoice_place_ua': place_ua,
            'invoice_bank_en': bank_name,
            'invoice_bank_ua': bank_name,
            'invoice_bic_swift_code': bic_swift,
            'invoice_iban': iban,
        })

        # ── Service agreement block ───────────────────────────────────────────
        if sa:
            ctx_data.update({
                'contract_id':                sa.name or '',
                'contract_conclusion_date':   _d(sa.date_signed),
                'sa_reference':               sa.name or '',
                'sa_date_signed':             _d(sa.date_signed),
                'sa_date_effective':          _d(sa.date_effective),
                'sa_date_termination':        _d(sa.date_termination),
                'sa_hourly_rate':             sa.hourly_rate,
                'sa_payment_banking_days':    sa.payment_banking_days,
                'sa_termination_notice_days': sa.termination_notice_days,
                'sa_currency':               sa.currency_id.name if sa.currency_id else '',
            })

        # ── Salary run block ──────────────────────────────────────────────────
        ctx = {
            'ctx': ctx_data,
            'salary_run': {
                'reference': run.reference or '',
                'date_start': _d(run.date_start),
                'date_end': _d(run.date_end),
                'total_hours': run.total_hours,
                'total_to_pay': amount,
                'currency': currency_name,
            },
            'invoice': {
                'hours': hours,
                'amount': amount,
                'hourly_rate': hourly_rate,
            },
        }

        # ── Company block ─────────────────────────────────────────────────────
        pay_duration = str(company.hpc_pay_duration) if company.hpc_pay_duration else ''
        rep_en = company.hpc_representative_id.name or company.name or ''
        rep_ua = company.hpc_representative_name_ua or rep_en
        p = company.partner_id
        city_zip = ' '.join(filter(None, [p.city, p.zip]))
        address_en = ', '.join(filter(None, [
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

        ctx['customer'] = {
            'incorporation_number': company.company_registry or '',
            'itn': company.vat or '',
            'signature': {'img': sig_img or None},
            'en': {'entity': {
                'legal_name': company.name or '',
                'registered_address': address_en,
                'representative': rep_en,
                'signature': rep_en,
                'pay_duration': pay_duration,
            }},
            'ua': {'entity': {
                'legal_name': company.hpc_legal_name_ua or company.name or '',
                'registered_address': address_en,
                'representative': rep_ua,
                'signature': rep_ua,
                'pay_duration': pay_duration,
            }},
        }

        rendered_vars = self._build_rendered_vars_html(ctx, sa)

        self.write({
            'hours_on_invoice': hours,
            'amount_on_invoice': amount,
            'context_data': json.dumps(ctx, default=str, indent=2),
            'rendered_vars_html': rendered_vars,
        })
        return ctx

    def _build_rendered_vars_html(self, ctx, sa):
        """Build a combined HTML table showing Jinja2 variables resolved from ctx
        for each of the three template slots (Invoice, Agreement, Termination)."""
        from odoo.addons.jito_document_template.services.docx_renderer import (  # noqa: PLC0415
            extract_jinja_variables, build_rendered_vars_html)

        tpl_rec = sa.template_id if sa else None
        if not tpl_rec:
            return False

        slots = [
            ('Invoice Template', 'inv_template_file'),
        ]

        html_parts = []
        for label, field_name in slots:
            file_b64 = tpl_rec.with_context(bin_size=False)[field_name]
            if not file_b64:
                html_parts.append(
                    '<p class="text-muted small mb-1">'
                    '<em>%s — no template uploaded.</em></p>' % label
                )
                continue
            try:
                variables = extract_jinja_variables(base64.b64decode(file_b64))
                table = build_rendered_vars_html(variables, ctx)
                html_parts.append(
                    '<h6 class="mt-3 mb-1 fw-bold">%s</h6>%s' % (label, table)
                )
            except Exception as e:
                html_parts.append(
                    '<p class="text-danger small">Could not parse %s: %s</p>'
                    % (label, str(e))
                )

        return ''.join(html_parts) or False

    # ── DOCX / PDF generation ─────────────────────────────────────────────────

    def action_generate_invoice_docs(self):
        """Rebuild context, render DOCX (+ PDF if LibreOffice), mark as generated."""
        self.ensure_one()
        from odoo.addons.jito_document_template.services.docx_renderer import (  # noqa: PLC0415
            render_docx, convert_to_pdf, is_libreoffice_available)

        run = self.salary_run_id
        if not run:
            raise UserError(_('No salary run linked to this invoice.'))
        contract = run.contract_id
        if not contract:
            raise UserError(_('No contract linked to the salary run.'))
        sa = contract.service_agreement_id
        if not sa or not sa.template_id:
            raise UserError(_(
                'No service agreement (with template) found on the contract. '
                'Link a service agreement first.'
            ))
        file_b64 = sa.template_id.with_context(bin_size=False).inv_template_file
        if not file_b64:
            raise UserError(_(
                'No invoice template (.docx) uploaded on the service agreement template. '
                'Upload it under the "Contractor Invoicing" tab.'
            ))

        # Rebuild context so hours/rate are up to date
        ctx = self.action_build_context()

        docx_bytes = render_docx(base64.b64decode(file_b64), ctx)

        # Use inv_output_filename Jinja2 template when set; fall back to default
        def _resolve_name(ext):
            tpl_str = sa.template_id.inv_output_filename
            if tpl_str:
                try:
                    from odoo.addons.jito_document_template.services.docx_renderer import (  # noqa: PLC0415
                        render_string)
                    name = render_string(tpl_str, ctx).strip()
                    if name:
                        base = name.rsplit('.', 1)[0] if '.' in name else name
                        return '%s.%s' % (base, ext)
                except Exception:
                    pass
            return 'invoice_%s.%s' % (self.name, ext)

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
            except Exception as e:
                _logger.warning('PDF conversion failed for invoice %s: %s', self.name, e)

        self.write({
            'generated_docx_id': docx_att.id,
            'generated_pdf_id': pdf_att.id if pdf_att else False,
            'state': 'generated',
        })

    # Backward-compat alias used by old views / tests
    def action_generate_docx(self):
        return self.action_generate_invoice_docs()

    # ── Sign flow ─────────────────────────────────────────────────────────────

    def action_send_for_signing(self):
        self.ensure_one()
        if not self.generated_pdf_id:
            raise UserError(_('Generate the invoice PDF first.'))
        sign_tpl = self.env['sign.template'].create(
            {'attachment_id': self.generated_pdf_id.id}
        )
        self.invoice_sign_template_id = sign_tpl.id
        return {
            'type': 'ir.actions.client',
            'tag': 'sign.Template',
            'params': {'id': sign_tpl.id, 'sign_directly_without_mail': False},
        }

    def action_view_signing(self):
        self.ensure_one()
        req = self.invoice_sign_request_id
        if not req:
            raise UserError(_('No signing request found for this invoice.'))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sign.request',
            'res_id': req.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_download_signed(self):
        self.ensure_one()
        req = self.invoice_sign_request_id
        if not req or req.state != 'signed':
            raise UserError(_('Invoice is not fully signed yet.'))
        att = req.completed_document_attachment_ids[:1]
        if not att:
            raise UserError(_('Signed document not found on the signing request.'))
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%d?download=true' % att.id,
            'target': 'self',
        }

    def action_reset_signing(self):
        """Cancel and fully delete the invoice signing chain."""
        self.ensure_one()
        tpl = self.invoice_sign_template_id
        if not tpl:
            return
        requests = tpl.sudo().sign_request_ids
        completed_atts = requests.mapped('completed_document_attachment_ids')
        requests.sudo().cancel()
        requests.sudo().unlink()
        tpl.sudo().unlink()
        completed_atts.sudo().unlink()
        self.invoice_sign_template_id = False

    # ── Download helpers ──────────────────────────────────────────────────────

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

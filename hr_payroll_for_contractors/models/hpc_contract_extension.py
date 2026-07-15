import re

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class HpcContractExtension(models.Model):
    _inherit = 'hr.payroll.contractor.contract'

    legal_entity_id = fields.Many2one(
        'hpc.contractor.legal.entity',
        string='Legal Entity',
        domain="[('contractor_id.employee_id', '=', employee_id)]",
        ondelete='set null',
    )
    payment_method_id = fields.Many2one(
        'hpc.contractor.payment.method',
        string='Payment Method',
        domain="[('contractor_id.employee_id', '=', employee_id)]",
        ondelete='set null',
    )
    # Non-stored: computed via SA.contract_id reverse lookup — no DB column, no FK constraint.
    service_agreement_id = fields.Many2one(
        'hpc.contract.service.agreement',
        string='Service Agreement',
        compute='_compute_service_agreement_id',
        inverse='_inverse_service_agreement_id',
        store=False,
    )

    @api.depends()
    def _compute_service_agreement_id(self):
        SA = self.env['hpc.contract.service.agreement']
        for rec in self:
            sa = SA.search([('contract_id', '=', rec.id)], limit=1)
            rec.service_agreement_id = sa or False

    def _inverse_service_agreement_id(self):
        SA = self.env['hpc.contract.service.agreement']
        for rec in self:
            sa = rec.service_agreement_id
            if sa and sa.contract_id != rec:
                sa.contract_id = rec

    # ── Override revolut fields as computed ───────────────────────────────────
    # These are originally defined in hpc_revolut_payments as plain Char/Many2one
    # fields. We override them here to be computed+stored from the attached
    # legal entity and payment method (SEPA or SWIFT).

    revolut_recipient_name = fields.Char(
        compute='_compute_revolut_from_entity',
        store=True,
    )
    revolut_iban = fields.Char(
        compute='_compute_revolut_from_entity',
        store=True,
    )
    revolut_bic = fields.Char(
        compute='_compute_revolut_from_entity',
        store=True,
    )
    revolut_bank_country_id = fields.Many2one(
        'res.country',
        compute='_compute_revolut_from_entity',
        store=True,
    )
    revolut_recipient_country_id = fields.Many2one(
        'res.country',
        compute='_compute_revolut_from_entity',
        store=True,
    )
    revolut_address_line1 = fields.Char(
        compute='_compute_revolut_from_entity',
        store=True,
    )
    revolut_address_line2 = fields.Char(
        compute='_compute_revolut_from_entity',
        store=True,
    )
    revolut_city = fields.Char(
        compute='_compute_revolut_from_entity',
        store=True,
    )
    revolut_postal_code = fields.Char(
        compute='_compute_revolut_from_entity',
        store=True,
    )

    @api.depends(
        'legal_entity_id',
        'legal_entity_id.ua_pe_addr_country_id',
        'legal_entity_id.ua_pe_addr_street1_en',
        'legal_entity_id.ua_pe_addr_street2_en',
        'legal_entity_id.ua_pe_addr_city_en',
        'legal_entity_id.ua_pe_addr_postal_code',
        'payment_method_id',
        'payment_method_id.method_type',
        'payment_method_id.sepa_recipient_name',
        'payment_method_id.sepa_iban',
        'payment_method_id.sepa_bic',
        'payment_method_id.sepa_bank_country_id',
        'payment_method_id.swift_recipient_name',
        'payment_method_id.swift_account_number',
        'payment_method_id.swift_bic',
        'payment_method_id.swift_bank_country_id',
    )
    def _compute_revolut_from_entity(self):
        for rec in self:
            le = rec.legal_entity_id
            pm = rec.payment_method_id

            # Recipient address always comes from the legal entity (person)
            rec.revolut_recipient_country_id = le.ua_pe_addr_country_id if le else False
            rec.revolut_address_line1 = le.ua_pe_addr_street1_en if le else False
            rec.revolut_address_line2 = le.ua_pe_addr_street2_en if le else False
            rec.revolut_city = le.ua_pe_addr_city_en if le else False
            rec.revolut_postal_code = le.ua_pe_addr_postal_code if le else False

            if pm and pm.method_type == 'sepa':
                rec.revolut_recipient_name = pm.sepa_recipient_name
                rec.revolut_iban = pm.sepa_iban
                rec.revolut_bic = pm.sepa_bic
                rec.revolut_bank_country_id = pm.sepa_bank_country_id
            elif pm and pm.method_type == 'swift':
                rec.revolut_recipient_name = pm.swift_recipient_name
                rec.revolut_iban = pm.swift_account_number
                rec.revolut_bic = pm.swift_bic
                rec.revolut_bank_country_id = pm.swift_bank_country_id
            else:
                rec.revolut_recipient_name = False
                rec.revolut_iban = False
                rec.revolut_bic = False
                rec.revolut_bank_country_id = False

    def action_create_service_agreement(self):
        """Open a new service agreement form pre-linked to this contract."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('New Service Agreement'),
            'res_model': 'hpc.contract.service.agreement',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_contract_id': self.id,
                'default_employee_id': self.employee_id.id,
                'default_legal_entity_id': self.legal_entity_id.id or False,
                'default_payment_method_id': self.payment_method_id.id or False,
            },
        }

    def action_open_service_agreement(self):
        """Open the linked service agreement in a dialog window."""
        self.ensure_one()
        if not self.service_agreement_id:
            raise UserError(_('No service agreement linked to this contract.'))
        return {
            'type': 'ir.actions.act_window',
            'name': self.service_agreement_id.name or _('Service Agreement'),
            'res_model': 'hpc.contract.service.agreement',
            'res_id': self.service_agreement_id.id,
            'view_mode': 'form',
            'target': 'new',
        }

    # ── Vendor (res.partner) from the contract's legal entity + payment method ──
    # The legal entity & payment method live on the CONTRACT, so a vendor can be
    # built without a service agreement.

    def _build_vendor_partner_vals(self):
        """res.partner values for the vendor, from the contract's legal entity +
        employee. Ukrainian PE vendors are named 'PE <First> <Last>'."""
        self.ensure_one()
        entity = self.legal_entity_id
        employee = self.employee_id
        name_parts = list(filter(None, [
            entity.ua_pe_first_name_en,
            entity.ua_pe_last_name_en,
        ]))
        if name_parts:
            partner_name = ' '.join(name_parts)
            if entity.entity_type == 'ua_pe':
                partner_name = 'PE ' + partner_name
        else:
            partner_name = employee.name if employee else entity.display_name
        email = phone = ''
        if employee:
            email = employee.work_email or employee.private_email or ''
            phone = employee.mobile_phone or employee.work_phone or ''
        return {
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

    def _payment_method_bank_details(self):
        """(acc_number, bic, bank_name, aba_routing) for the selected payment
        method, or (False, False, False, False) when it has no bank account
        (card/cash/crypto). ``aba_routing`` is only set for US ACH — a routing
        number is NOT a BIC, so it goes in the native res.partner.bank
        ``aba_routing`` field (from l10n_us), never in ``bank_bic``."""
        self.ensure_one()
        pm = self.payment_method_id
        if not pm:
            return False, False, False, False
        if pm.method_type == 'sepa':
            return pm.sepa_iban, pm.sepa_bic, pm.sepa_bank_name, False
        if pm.method_type == 'swift':
            return pm.swift_account_number, pm.swift_bic, pm.swift_bank_name, False
        if pm.method_type == 'gbp':
            return pm.gbp_account_number, False, pm.gbp_bank_name, False
        if pm.method_type == 'ach':
            return pm.ach_account_number, False, pm.ach_bank_name, pm.ach_routing_number
        return False, False, False, False

    def _ensure_payment_bank(self, partner):
        """Idempotent get-or-create of the res.partner.bank for the selected
        payment method on `partner`. Empty recordset if there's no bank account."""
        self.ensure_one()
        Bank = self.env['res.partner.bank']
        acc_number, bic, bank_name_val, aba_routing = self._payment_method_bank_details()
        if not acc_number:
            return Bank
        sanitized = re.sub(r'\W+', '', acc_number).upper()
        bank = Bank.search([
            ('sanitized_acc_number', '=', sanitized),
            ('partner_id', '=', partner.id),
        ], limit=1)
        if bank:
            return bank
        vals = {'acc_number': acc_number, 'partner_id': partner.id, 'allow_out_payment': True}
        if bic:
            vals['bank_bic'] = bic
        if bank_name_val:
            vals['bank_name'] = bank_name_val
        if aba_routing:
            vals['aba_routing'] = aba_routing
        return Bank.create(vals)

    def _enrich_vendor(self, partner):
        """Back-fill ONLY empty core fields on an existing vendor (never overwrites)."""
        self.ensure_one()
        entity = self.legal_entity_id
        if not entity:
            return
        candidates = {
            'vat': entity.ua_vat_itn,
            'street': entity.ua_pe_addr_street1_en,
            'street2': entity.ua_pe_addr_street2_en,
            'city': entity.ua_pe_addr_city_en,
            'zip': entity.ua_pe_addr_postal_code,
            'country_id': entity.ua_pe_addr_country_id.id if entity.ua_pe_addr_country_id else False,
        }
        vals = {f: v for f, v in candidates.items() if v and not partner[f]}
        if vals:
            partner.write(vals)

    def _find_existing_vendor(self):
        """Find an already-created vendor for this contract: the service
        agreement's vendor first, then by the legal entity's VAT, then by name."""
        self.ensure_one()
        Partner = self.env['res.partner']
        sa = self.service_agreement_id
        if sa and sa.vendor_id:
            return sa.vendor_id
        vat = (self.legal_entity_id.ua_vat_itn or '').strip()
        if vat:
            found = Partner.search(
                [('vat', '=ilike', vat), ('supplier_rank', '>', 0)], limit=1)
            if found:
                return found
        name = self._build_vendor_partner_vals().get('name')
        if name:
            found = Partner.search(
                [('name', '=ilike', name), ('supplier_rank', '>', 0)], limit=1)
            if found:
                return found
        return Partner

    def _ensure_payroll_vendor(self):
        """Ensure a fully-populated vendor partner + recipient bank for this
        contract, built from its legal entity + payment method (no OCR, NO service
        agreement required). Returns (partner, bank)."""
        self.ensure_one()
        if not self.legal_entity_id:
            raise UserError(_(
                'Cannot determine the vendor for contract "%s": set a Legal Entity '
                '(and a payment method) on the contract.', self.display_name))
        partner = self._find_existing_vendor()
        if partner:
            self._enrich_vendor(partner)
        else:
            partner = self.env['res.partner'].create(self._build_vendor_partner_vals())
            if self.employee_id and not self.employee_id.work_contact_id:
                self.employee_id.work_contact_id = partner.id
            pm = self.payment_method_id
            partner.message_post(body=_(
                'Vendor generated from contractor legal entity <b>%s</b> and '
                'payment method <b>%s</b>.',
                self.legal_entity_id.display_name or '—',
                pm.display_name if pm else '—'))
        # Keep the service agreement's vendor_id in sync when an SA exists.
        sa = self.service_agreement_id
        if sa and not sa.vendor_id:
            sa.vendor_id = partner.id
        bank = self._ensure_payment_bank(partner)
        return partner, bank

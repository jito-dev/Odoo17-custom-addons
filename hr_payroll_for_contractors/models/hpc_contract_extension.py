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

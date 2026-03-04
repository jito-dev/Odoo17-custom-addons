from odoo import fields, models


class HpcContractRevolut(models.Model):
    _inherit = 'hr.payroll.contractor.contract'

    revolut_recipient_name = fields.Char(string='Recipient Entity Legal Name')
    revolut_iban = fields.Char(string='IBAN')
    revolut_bic = fields.Char(string='BIC')
    revolut_bank_country_id = fields.Many2one(
        'res.country', string='Recipient Bank Country', ondelete='restrict')
    revolut_recipient_country_id = fields.Many2one(
        'res.country', string='Recipient Country', ondelete='restrict')
    revolut_address_line1 = fields.Char(string='Address Line 1')
    revolut_address_line2 = fields.Char(string='Address Line 2')
    revolut_city = fields.Char(string='City')
    revolut_postal_code = fields.Char(string='Postal Code')

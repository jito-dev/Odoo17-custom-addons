from odoo import _, fields, models


class PaymentProvider(models.Model):
    _inherit = 'payment.provider'

    transfer_contact_email = fields.Char(
        string="Transfer Contact Email",
        help="The address shown on the portal for questions about a bank transfer. Left empty, "
             "the contact line is not shown at all — an address nobody reads is worse than none.",
    )
    transfer_purpose_template = fields.Char(
        string="Payment Purpose",
        default=lambda self: _("{services} – Invoice {reference}"),
        help="The shape of the line the customer writes in the purpose field of their bank. "
             "'{services}' is replaced with what the invoice is for — its own Payment Purpose "
             "if it has one, otherwise the products on it; '{reference}' with the payment "
             "reference. Anything else is copied as it is. The result is cut to the 140 "
             "characters a bank transfer carries, and only '{services}' is shortened, so the "
             "reference always survives.",
    )

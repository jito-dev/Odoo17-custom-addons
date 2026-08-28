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
        default=lambda self: _("Software development services – Invoice {reference}"),
        help="What the customer is told to write in the purpose field of their bank. "
             "'{reference}' is replaced with the payment reference of the invoice; anything else "
             "is copied as it is.",
    )

from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    transfer_purpose_name = fields.Char(
        string="Payment Purpose Name",
        help="How this product is named in the payment purpose the customer writes into their "
             "bank when paying an invoice by transfer. Left empty, the product name is used. "
             "Fill it in when the catalogue name is not what should reach a bank — an internal "
             "code, a name too long for the 140 characters a transfer carries, or wording the "
             "customer's accountant would not recognise.",
    )

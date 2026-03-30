from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    ai_invoice_extract_mode = fields.Selection(
        selection=[
            ('no_send', 'Do not extract'),
            ('manual_send', 'Extract on demand only'),
            ('auto_send', 'Extract automatically'),
        ],
        string="AI Invoice Extraction",
        required=True,
        default='manual_send',
        help="Determines how uploaded vendor bill PDFs are processed:\n"
             "- Do not extract: Feature disabled.\n"
             "- Extract on demand only: Shows 'Extract with AI' button.\n"
             "- Extract automatically: Extracts on PDF upload.",
    )

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    ai_invoice_extract_mode = fields.Selection(
        related='company_id.ai_invoice_extract_mode',
        string='AI Invoice Extraction',
        readonly=False,
        required=True,
    )

    # Reuse OpenAI fields from hr_recruitment_extract_openai
    openai_api_key = fields.Char(
        related='company_id.openai_api_key',
        string="OpenAI API Key",
        readonly=False,
    )

    openai_model = fields.Char(
        related='company_id.openai_model',
        string="OpenAI Model",
        readonly=False,
    )

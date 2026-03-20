import uuid

from odoo import api, fields, models


class ResCompanyCard(models.Model):
    _inherit = 'res.company'

    card_share_token = fields.Char(
        string='Card Share Token',
        copy=False,
        default=lambda self: uuid.uuid4().hex,
        help='Unique token used in the public company card URL.',
    )
    card_published = fields.Boolean(
        string='Publish Company Card',
        default=False,
        help='When enabled, the company card is publicly accessible via the share URL.',
    )
    card_hide_header_footer = fields.Boolean(
        string='Hide Header & Footer',
        default=True,
        help='Hide the website header and footer on the public company card page.',
    )
    card_registration_number = fields.Char(
        string='Registration Number',
        help='Company registration number displayed on the public card.',
    )
    card_registration_date = fields.Date(
        string='Registration Date',
        help='Company registration date displayed on the public card.',
    )
    card_share_url = fields.Char(
        string='Card Share URL',
        compute='_compute_card_share_url',
    )

    @api.depends('card_share_token')
    def _compute_card_share_url(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        for company in self:
            if company.card_share_token:
                company.card_share_url = f'{base_url}/company/card/{company.card_share_token}'
            else:
                company.card_share_url = False

    def action_regenerate_card_token(self):
        for company in self:
            company.card_share_token = uuid.uuid4().hex

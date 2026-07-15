# -*- coding: utf-8 -*-
from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    upwork_address_enrich_state = fields.Selection(
        selection=[
            ('none', '—'),
            ('pending', 'Pending'),
            ('done', 'Done'),
            ('failed', 'Failed'),
        ],
        string='Upwork Address Enrichment',
        default='none', copy=False,
        help='Tracks AI billing-address enrichment from Upwork invoices. Set to '
             '"pending" the moment a job is queued so the same client is enriched '
             'only once.',
    )

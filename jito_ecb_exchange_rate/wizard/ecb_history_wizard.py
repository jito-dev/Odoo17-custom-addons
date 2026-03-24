# -*- coding: utf-8 -*-
import logging

import requests

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from ..models.res_company import ECB_URL_HIST_90D, ECB_URL_HIST_FULL

_logger = logging.getLogger(__name__)

SOURCE_SELECTION = [
    ('hist_90d', 'Last 90 days'),
    ('hist_full', 'Full history (since 1999)'),
]


class EcbRateHistoryWizard(models.TransientModel):
    _name = 'ecb.rate.history.wizard'
    _description = 'ECB Historical Rates Download Wizard'

    date_from = fields.Date(
        string='Date From',
        required=True,
    )
    date_to = fields.Date(
        string='Date To',
        required=True,
        default=fields.Date.context_today,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        readonly=True,
    )
    source = fields.Selection(
        selection=SOURCE_SELECTION,
        string='ECB Data Source',
        default='hist_90d',
        required=True,
    )
    status_message = fields.Text(
        string='Result',
        readonly=True,
    )

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for wizard in self:
            if wizard.date_from and wizard.date_to and wizard.date_from > wizard.date_to:
                raise UserError(_("'Date From' must be earlier than or equal to 'Date To'."))

    def action_download(self):
        """Download historical ECB rates for the selected date range."""
        self.ensure_one()

        url = ECB_URL_HIST_90D if self.source == 'hist_90d' else ECB_URL_HIST_FULL

        try:
            parsed_data = self.company_id._ecb_fetch_rates_xml(url)
        except requests.exceptions.RequestException as e:
            raise UserError(_(
                "Failed to fetch ECB historical rates: %s", str(e)
            )) from e

        created, updated = self.company_id._ecb_upsert_rates(
            parsed_data,
            date_from=self.date_from,
            date_to=self.date_to,
        )

        self.status_message = _(
            "Download complete.\n"
            "Created: %d rate(s)\n"
            "Updated: %d rate(s)\n"
            "Date range: %s to %s",
            created, updated,
            self.date_from, self.date_to,
        )

        # Return the same wizard form so user sees the result
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

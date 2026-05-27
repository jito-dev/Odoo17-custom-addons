import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ScaSettings(models.Model):
    _name = 'sca.settings'
    _description = 'Simple Crypto Accounting Settings'

    lock_field = fields.Char(default='global', copy=False)
    etherscan_api_key = fields.Char(string='Etherscan API Key', copy=False,
        help="Required for ERC-20 watched addresses. Get one free at etherscan.io/apis.")
    trongrid_api_key = fields.Char(string='TronGrid API Key (legacy)',
        copy=False,
        help="Deprecated in 17.0.4.0.0. Retained for migration safety; "
             "not exposed in the UI.")
    cryptoapis_api_key = fields.Char(string='CryptoAPIs API Key (legacy)',
        copy=False,
        help="Deprecated in 17.0.5.0.0 — CryptoAPIs's REST API doesn't "
             "expose TRC-20 transfer listings. Retained for migration "
             "safety; not exposed in the UI.")
    tronscan_api_key = fields.Char(string='Tronscan API Key (optional)',
        copy=False,
        help="Optional for TRC-20 watched addresses (17.0.5.0.0). "
             "Tronscan's public API works without a key for low volume "
             "(rate-limited per IP). For higher throughput, get one at "
             "tronscan.org and we'll send it as the `TRON-PRO-API-KEY` "
             "header to https://apilist.tronscanapi.com/api/.")
    last_sync_date = fields.Datetime(string='Last Sync', readonly=True)

    _sql_constraints = [
        ('singleton', 'UNIQUE(lock_field)', 'Only one Crypto Accounting settings record is allowed.'),
    ]

    @api.model
    def _get_singleton(self):
        record = self.sudo().search([], limit=1)
        if not record:
            record = self.sudo().create({'etherscan_api_key': ''})
        return record

    def action_open_settings(self):
        record = self._get_singleton()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Crypto Accounting Settings'),
            'res_model': 'sca.settings',
            'res_id': record.id,
            'view_mode': 'form',
            'target': 'current',
        }

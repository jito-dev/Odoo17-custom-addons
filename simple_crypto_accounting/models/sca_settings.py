import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ScaSettings(models.Model):
    _name = 'sca.settings'
    _description = 'Simple Crypto Accounting Settings'

    lock_field = fields.Char(default='global', copy=False)
    etherscan_api_key = fields.Char(string='Etherscan API Key', required=True, copy=False)
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

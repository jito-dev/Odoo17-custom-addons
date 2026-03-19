from odoo import models, fields


class ScaToken(models.Model):
    _name = 'sca.token'
    _description = 'Watched ERC-20 Token Contract'
    _order = 'name'

    watched_address_id = fields.Many2one(
        'sca.watched_address',
        string='Watched Address',
        required=True,
        ondelete='cascade',
    )
    name = fields.Char(string='Token Symbol', required=True, help='e.g. USDT, USDC, DAI')
    contract_address = fields.Char(
        string='Contract Address',
        required=True,
        help='ERC-20 token contract address (0x...)',
    )
    decimals = fields.Integer(string='Decimals', default=18, help='Token decimal places (usually 18, USDT/USDC use 6)')
    balance = fields.Float(string='Balance', digits=(30, 8), readonly=True)

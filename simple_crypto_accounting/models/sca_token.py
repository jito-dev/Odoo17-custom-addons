from odoo import api, models, fields


class ScaToken(models.Model):
    _name = 'sca.token'
    _description = 'Watched ERC-20 / TRC-20 Token Contract'
    _order = 'name'

    watched_address_id = fields.Many2one(
        'sca.watched_address',
        string='Watched Address',
        required=True,
        ondelete='cascade',
    )
    # Stored related to the parent's network so the preset domain can
    # filter by it (One2many tree lines can't reach `parent.network`
    # via field domains in Odoo 17 — they need a field on `self`).
    parent_network = fields.Selection(
        related='watched_address_id.network',
        store=True,
        readonly=True,
    )
    preset_id = fields.Many2one(
        'sca.token.preset',
        string='Preset',
        domain="[('network', '=', parent_network)]",
        help="Pick a well-known token to auto-fill Symbol, Contract "
             "Address, and Decimals. Leave blank to enter values "
             "manually. Manage presets at Configuration → Token Presets.",
    )
    name = fields.Char(
        string='Token Symbol', required=True,
        help='e.g. USDT, USDC, DAI',
    )
    contract_address = fields.Char(
        string='Contract Address', required=True,
        help='ERC-20: 0x-hex (40 chars); TRC-20: T-base58 (~34 chars).',
    )
    decimals = fields.Integer(
        string='Decimals', default=18,
        help='Token decimal places. USDT/USDC use 6; most others use 18.',
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        ondelete='restrict',
        help='The res.currency record representing this token. Pulled '
             'over from the chosen Preset; can be set manually for '
             'tokens that don\'t have a preset yet. Used by '
             'sca.mgt.ledger.map and the management-ledger injection '
             'to denominate generated moves in the right currency.',
    )
    balance = fields.Float(string='Balance', digits=(30, 8), readonly=True)

    @api.onchange('preset_id')
    def _onchange_preset_id(self):
        """Auto-fill Symbol, Contract Address, Decimals, and Currency
        when the user picks a preset. Existing values are overwritten —
        the whole point is to use the preset's authoritative values.
        """
        if not self.preset_id:
            return
        self.name = self.preset_id.symbol
        self.contract_address = self.preset_id.contract_address
        self.decimals = self.preset_id.decimals
        self.currency_id = self.preset_id.currency_id

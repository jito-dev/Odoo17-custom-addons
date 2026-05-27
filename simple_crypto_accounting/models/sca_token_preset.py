# -*- coding: utf-8 -*-

from odoo import api, fields, models


class ScaTokenPreset(models.Model):
    """Registry of well-known token contracts per network (17.0.3.1.0).

    Picking a preset on a new ``sca.token`` row auto-fills its symbol,
    contract address, and decimals — so users don't have to look up
    USDC's contract address every time.

    Seeded with the common stablecoins via ``data/sca_token_preset.xml``
    (noupdate=1; user edits are preserved on upgrade). Admins can add
    more entries via **Configuration → Token Presets**.
    """

    _name = 'sca.token.preset'
    _description = 'Crypto Token Preset'
    _order = 'network, symbol'

    name = fields.Char(
        string='Display Name',
        required=True,
        help="Human-readable label shown in the dropdown — e.g. "
             "'USDC (Ethereum)'.",
    )
    symbol = fields.Char(
        string='Symbol',
        required=True,
        help="Token symbol, e.g. USDC, USDT, DAI.",
    )
    network = fields.Selection(
        [('erc20', 'ERC-20 (Ethereum)'),
         ('trc20', 'TRC-20 (TRON)')],
        string='Network',
        required=True,
    )
    contract_address = fields.Char(
        string='Contract Address',
        required=True,
        help="On-chain contract address. ERC-20: 0x-hex; TRC-20: T-base58.",
    )
    decimals = fields.Integer(
        string='Decimals',
        required=True,
        default=18,
        help="Token decimal places. Most stablecoins use 6; most "
             "other ERC-20 / TRC-20 tokens use 18.",
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        ondelete='restrict',
        help="The res.currency record this preset represents. Pre-set "
             "for the seeded crypto presets (USDC, USDT, DAI, BTC, ETH); "
             "leave blank for tokens you don't want to track as proper "
             "currencies. Picking a preset on a sca.token row pulls "
             "this value over so the watched token gets the right "
             "currency for downstream accounting integration.",
    )
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('unique_network_contract',
         'UNIQUE(network, contract_address)',
         'A token contract can be listed only once per network.'),
    ]

    @api.depends('symbol', 'network')
    def _compute_display_name(self):
        net_label = dict(self._fields['network']._description_selection(self.env))
        for rec in self:
            rec.display_name = '%s (%s)' % (
                rec.symbol or rec.name or '?',
                net_label.get(rec.network) or rec.network or '',
            )

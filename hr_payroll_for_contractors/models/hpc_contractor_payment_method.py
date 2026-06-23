from odoo import fields, models


class HpcContractorPaymentMethod(models.Model):
    _name = 'hpc.contractor.payment.method'
    _description = 'Contractor Payment Method'
    _order = 'contractor_id, method_type'

    name = fields.Char(string='Name', placeholder='e.g. PE Monobank USD')
    contractor_id = fields.Many2one(
        'hpc.contractor',
        string='Contractor',
        required=True,
        ondelete='cascade',
    )
    legal_entity_id = fields.Many2one(
        'hpc.contractor.legal.entity',
        string='Legal Entity',
        domain="[('contractor_id', '=', contractor_id)]",
        ondelete='set null',
    )
    method_type = fields.Selection(
        selection=[
            ('sepa', 'SEPA Bank Transfer (IBAN)'),
            ('swift', 'SWIFT (International)'),
            ('gbp', 'GBP Payments (UK)'),
            ('ua_bank_card', 'Ukrainian Bank Card'),
            ('cash', 'Cash'),
            ('crypto', 'Crypto Payments'),
        ],
        string='Method',
        required=True,
        default='sepa',
    )

    # ── SEPA Bank Transfer ────────────────────────────────────────────────────
    sepa_recipient_name = fields.Char(string='Recipient Name')
    sepa_iban = fields.Char(string='IBAN')
    sepa_bic = fields.Char(string='BIC / SWIFT')
    sepa_bank_name = fields.Char(string='Bank Name')
    sepa_bank_country_id = fields.Many2one(
        'res.country', string='Bank Country', ondelete='restrict')
    sepa_currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.ref('base.EUR', raise_if_not_found=False),
        readonly=True,
        ondelete='restrict',
    )

    # ── SWIFT (International) ─────────────────────────────────────────────────
    swift_recipient_name = fields.Char(string='Recipient Name')
    swift_account_number = fields.Char(string='Account Number or IBAN')
    swift_bic = fields.Char(string='SWIFT / BIC')
    swift_bank_name = fields.Char(string='Bank Name')
    swift_bank_address = fields.Char(string='Bank Address')
    swift_bank_country_id = fields.Many2one(
        'res.country', string='Bank Country', ondelete='restrict')
    swift_currency_id = fields.Many2one(
        'res.currency', string='Currency', ondelete='restrict')

    # ── GBP Payments (UK) ─────────────────────────────────────────────────────
    gbp_recipient_name = fields.Char(string='Recipient Name')
    gbp_sort_code = fields.Char(string='Sort Code', help='Format: XX-XX-XX')
    gbp_account_number = fields.Char(string='Account Number')
    gbp_bank_name = fields.Char(string='Bank Name')
    gbp_currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.ref('base.GBP', raise_if_not_found=False),
        readonly=True,
        ondelete='restrict',
    )

    # ── Ukrainian Bank Card ───────────────────────────────────────────────────
    ua_card_number = fields.Char(
        string='Card Number',
        help='16-digit card number.',
    )
    ua_card_receiver_name = fields.Char(
        string='Receiver Name',
        help='e.g. Ivan Petrenko',
    )
    ua_card_currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        ondelete='restrict',
    )

    # ── Cash ──────────────────────────────────────────────────────────────────
    cash_currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        ondelete='restrict',
    )

    # ── Crypto Payments ───────────────────────────────────────────────────────
    crypto_wallet_address = fields.Char(string='Wallet Address')
    crypto_network = fields.Selection(
        selection=[('erc20', 'ERC-20 (Ethereum)')],
        string='Network',
        default='erc20',
    )
    crypto_token = fields.Selection(
        selection=[('usdc', 'USDC'), ('usdt', 'USDT')],
        string='Token',
    )
    crypto_fiat_currency_id = fields.Many2one(
        'res.currency',
        string='Fiat Currency for Accounting',
        default=lambda self: self.env.ref('base.USD', raise_if_not_found=False),
        readonly=True,
        ondelete='restrict',
    )

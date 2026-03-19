from odoo import models, fields, api


class ScaTransaction(models.Model):
    _name = 'sca.transaction'
    _description = 'Crypto Transaction'
    _order = 'tx_date desc, id desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    watched_address_id = fields.Many2one(
        'sca.watched_address',
        string='Watched Address',
        required=True,
        ondelete='cascade',
        index=True,
    )
    token_id = fields.Many2one(
        'sca.token',
        string='Token',
        ondelete='set null',
        index=True,
    )
    tx_hash = fields.Char(string='Transaction Hash', required=True, index=True, copy=False)
    log_index = fields.Integer(
        string='Log Index',
        default=-1,
        help='ERC-20 event log index within the transaction. -1 for native ETH transfers.',
    )
    block_number = fields.Integer(string='Block Number', readonly=True)
    tx_date = fields.Datetime(string='Date', readonly=True)
    from_address = fields.Char(string='From Address', readonly=True)
    to_address = fields.Char(string='To Address', readonly=True)
    raw_value = fields.Char(string='Raw Value', readonly=True, help='Value in smallest token unit (wei / base units)')
    token_symbol = fields.Char(string='Token', readonly=True)
    token_contract = fields.Char(string='Token Contract', readonly=True)
    gas_used = fields.Integer(string='Gas Used', readonly=True)

    etherscan_url = fields.Char(
        string='View on Etherscan',
        compute='_compute_etherscan_url',
        store=False,
    )
    description = fields.Text(string='Description', tracking=True)
    attachment_ids = fields.Many2many(
        'ir.attachment',
        'sca_transaction_attachment_rel',
        'transaction_id',
        'attachment_id',
        string='File Attachments',
    )

    value_decimal = fields.Float(
        string='Amount',
        compute='_compute_value_decimal',
        digits=(30, 8),
        store=True,
    )
    direction = fields.Selection(
        [('in', 'Incoming'), ('out', 'Outgoing')],
        string='Direction',
        compute='_compute_direction',
        store=True,
    )
    from_display = fields.Char(
        string='From',
        compute='_compute_display_addresses',
        store=False,
    )
    to_display = fields.Char(
        string='To',
        compute='_compute_display_addresses',
        store=False,
    )

    _sql_constraints = [
        ('unique_tx_hash', 'UNIQUE(tx_hash)', 'Transaction hash must be unique.'),
    ]

    @api.depends('tx_hash')
    def _compute_etherscan_url(self):
        for rec in self:
            rec.etherscan_url = 'https://etherscan.io/tx/%s' % rec.tx_hash if rec.tx_hash else False

    @api.depends('raw_value', 'token_id')
    def _compute_value_decimal(self):
        for rec in self:
            try:
                decimals = rec.token_id.decimals if rec.token_id else 18
                rec.value_decimal = int(rec.raw_value or '0') / (10 ** decimals)
            except (ValueError, TypeError):
                rec.value_decimal = 0.0

    @api.depends('to_address', 'watched_address_id')
    def _compute_direction(self):
        for rec in self:
            watched = (rec.watched_address_id.address or '').lower()
            to_addr = (rec.to_address or '').lower()
            rec.direction = 'in' if to_addr == watched else 'out'

    @api.depends('from_address', 'to_address')
    def _compute_display_addresses(self):
        # Load all known addresses once for the batch
        known = {
            r.address.lower(): r.name
            for r in self.env['sca.known_address'].sudo().search([])
        }
        for rec in self:
            from_addr = (rec.from_address or '').lower()
            to_addr = (rec.to_address or '').lower()
            rec.from_display = known.get(from_addr, rec.from_address or '')
            rec.to_display = known.get(to_addr, rec.to_address or '')

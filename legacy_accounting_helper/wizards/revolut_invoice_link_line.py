from odoo import api, fields, models


class RevolutInvoiceLinkLine(models.TransientModel):
    _name = 'revolut.invoice.link.line'
    _description = 'Proposed Revolut transaction ↔ customer invoice link'
    _order = 'id'

    wizard_id = fields.Many2one(
        'revolut.invoice.link.wizard', required=True, ondelete='cascade')
    transaction_id = fields.Many2one(
        'revolut.transaction', string='Transaction', required=True, readonly=True)

    # Display helpers (read-only mirrors of the transaction).
    tx_amount = fields.Float(related='transaction_id.amount', readonly=True)
    tx_currency = fields.Char(related='transaction_id.currency', readonly=True)
    tx_date = fields.Date(related='transaction_id.settlement_date_local', readonly=True)
    tx_description = fields.Char(related='transaction_id.description', readonly=True)
    tx_reference = fields.Char(related='transaction_id.reference', readonly=True)
    already_injected = fields.Boolean(compute='_compute_already_injected')

    proposed_invoice_id = fields.Many2one(
        'account.move', string='Customer Invoice',
        domain="[('move_type', '=', 'out_invoice')]")
    invoice_state = fields.Selection(related='proposed_invoice_id.state', readonly=True)
    confidence = fields.Selection(
        [('high', 'High'), ('medium', 'Medium'), ('low', 'Low'), ('none', 'No match')],
        default='none')
    match_reason = fields.Char()
    do_attach = fields.Boolean(string='Attach', default=False)

    @api.depends('transaction_id.statement_line_id')
    def _compute_already_injected(self):
        for line in self:
            line.already_injected = bool(line.transaction_id.statement_line_id)

    @api.onchange('proposed_invoice_id')
    def _onchange_proposed_invoice_id(self):
        # Tick "Attach" automatically when an invoice is (re)selected.
        for line in self:
            line.do_attach = bool(line.proposed_invoice_id)

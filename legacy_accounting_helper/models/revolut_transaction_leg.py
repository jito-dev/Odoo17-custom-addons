from odoo import fields, models


class RevolutTransactionLeg(models.Model):
    _name = 'revolut.transaction.leg'
    _description = 'Revolut Transaction Leg'
    _order = 'id'
    _rec_name = 'leg_id'

    transaction_id = fields.Many2one(
        'revolut.transaction',
        string='Transaction',
        required=True,
        ondelete='cascade',
        index=True,
    )
    leg_id = fields.Char(string='Leg ID', readonly=True)
    amount = fields.Float(string='Amount', digits=(16, 4), readonly=True)
    fee = fields.Float(string='Fee', digits=(16, 4), readonly=True)
    currency = fields.Char(string='Currency', size=3, readonly=True)
    bill_amount = fields.Float(string='Bill Amount', digits=(16, 4), readonly=True)
    bill_currency = fields.Char(string='Bill Currency', size=3, readonly=True)
    account_id = fields.Char(string='Account ID', readonly=True)
    counterparty_id = fields.Char(string='Counterparty ID', readonly=True)
    counterparty_account_id = fields.Char(string='Counterparty Account ID', readonly=True)
    counterparty_account_type = fields.Char(string='Counterparty Type', readonly=True)
    description = fields.Char(string='Description', readonly=True)
    balance = fields.Float(string='Balance After', digits=(16, 4), readonly=True)

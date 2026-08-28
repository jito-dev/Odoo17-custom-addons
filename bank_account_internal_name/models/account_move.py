from odoo import api, fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    # Two-way live mirror of partner_bank_id (the "Recipient Bank"). partner_bank_id
    # is itself a computed-but-editable field, so a writable `related` wouldn't push
    # back live in the form — we use compute (load/reflect) + onchange (live push in
    # the form) + inverse (write-through for ORM/imports) so the two fields always
    # point at the same record, whichever one you set.
    recipient_bank_internal_id = fields.Many2one(
        'res.partner.bank',
        string='Recipient Bank Internal Name',
        compute='_compute_recipient_bank_internal_id',
        inverse='_inverse_recipient_bank_internal_id',
        readonly=False,
        store=True,  # stored so a user edit isn't recomputed-away during onchange
        help='Pick the Recipient Bank by its Internal Name — it sets the '
             'Recipient Bank field above to the same account (and vice-versa).',
    )

    @api.depends('partner_bank_id')
    def _compute_recipient_bank_internal_id(self):
        for move in self:
            move.recipient_bank_internal_id = move.partner_bank_id

    def _inverse_recipient_bank_internal_id(self):
        for move in self:
            move.partner_bank_id = move.recipient_bank_internal_id

    @api.onchange('recipient_bank_internal_id')
    def _onchange_recipient_bank_internal_id(self):
        # Live mirror in the form: selecting here updates Recipient Bank immediately.
        for move in self:
            if move.partner_bank_id != move.recipient_bank_internal_id:
                move.partner_bank_id = move.recipient_bank_internal_id

    @api.depends('bank_partner_id', 'currency_id')
    def _compute_partner_bank_id(self):
        """Override of `account` to prefer a bank account in the document currency.

        Stock Odoo picks the first bank account of the partner, trusted ones first,
        and never looks at the currency (`account/models/account_move.py:892`). With
        several company accounts that means a USD invoice happily shows the EUR
        account — or an old account with no currency at all, which is how every
        invoice up to INV/2026/00332 ended up printed with `test-to-delete`.

        Here an account whose currency equals the document's wins. Ties are broken
        by `sequence`, so which of two same-currency accounts is the default stays a
        configuration choice (drag them in the bank accounts list) instead of an
        accident of creation order. When no account matches the currency, the stock
        result is kept untouched: a currency without an account of its own must
        still get a bank, not an empty field.

        `currency_id` is in the dependencies on purpose: changing the currency of a
        draft invoice re-picks the account, overwriting a manual choice. The
        alternative — remembering that a human picked this one — needs a flag of its
        own, and a bank account left over from the previous currency is a worse
        default than one the accountant can simply pick again. The field stays
        `readonly=False`, so any account can still be selected by hand, including
        one in another currency.
        """
        super()._compute_partner_bank_id()
        for move in self:
            if not move.currency_id:
                continue
            matching = move.bank_partner_id.bank_ids.filtered(
                lambda bank: (
                    bank.currency_id == move.currency_id
                    and (not bank.company_id or bank.company_id == move.company_id)
                )
            )
            if matching:
                move.partner_bank_id = matching.sorted(
                    lambda bank: (not bank.allow_out_payment, bank.sequence, bank.id)
                )[:1]

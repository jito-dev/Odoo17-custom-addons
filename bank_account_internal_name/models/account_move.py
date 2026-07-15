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

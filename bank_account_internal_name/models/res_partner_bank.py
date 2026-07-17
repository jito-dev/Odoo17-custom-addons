from odoo import api, fields, models


class ResPartnerBank(models.Model):
    _inherit = 'res.partner.bank'

    # Make name_search match the internal name too (base default is just the
    # _rec_name = 'acc_number'). So typing "jito.eur" in any bank selector —
    # the invoice Recipient Bank, payments, statements — finds this account.
    _rec_names_search = ['acc_number', 'internal_name']

    # Relax the base uniqueness (acc_number + partner) to also include the currency,
    # so multi-currency banks like Revolut/Wise — one IBAN, several currency pockets —
    # can be created as one account per currency (each → its own bank journal).
    # Same name as the base constraint ('unique_number') so this *replaces* it
    # (Odoo merges _sql_constraints by name; -u drops the old one and adds this).
    _sql_constraints = [(
        'unique_number',
        'unique(sanitized_acc_number, partner_id, currency_id)',
        'The combination Account Number / Partner / Currency must be unique.',
    )]

    internal_name = fields.Char(
        string='Internal Name',
        index=True,
        help='Human-friendly internal label for this bank account '
             '(e.g. "jito.eur.internal"). Type it in any bank-account selector '
             '(Recipient Bank, payments, etc.) to find this account quickly. '
             'Internal only — it is not used on payment files or printed documents.',
    )

    linked_journal_id = fields.Many2one(
        'account.journal',
        string='Bank Journal',
        compute='_compute_linked_journal_id',
        help='The bank journal this account is bound to, if any. While a journal is '
             'linked, the account cannot be deleted on its own — archive or detach the '
             'journal first.',
    )

    @api.depends('journal_id')
    def _compute_linked_journal_id(self):
        # `journal_id` is the readonly One2many added by the account module
        # (account.journal.bank_account_id), constrained to at most one journal.
        for bank in self:
            bank.linked_journal_id = bank.journal_id[:1]

    @api.depends('acc_number', 'internal_name')
    @api.depends_context('bank_by_internal_name')
    def _compute_display_name(self):
        """Default display stays the IBAN (so nothing leaks onto documents). When a
        field opts in with context `bank_by_internal_name=1` (the invoice's
        'Recipient Bank Internal Name'), show the internal name instead."""
        super()._compute_display_name()
        if self.env.context.get('bank_by_internal_name'):
            for bank in self:
                if bank.internal_name:
                    bank.display_name = bank.internal_name

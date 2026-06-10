# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class ScaMgtLedgerMap(models.Model):
    """Maps a (watched_address, token) pair to its destination in the
    management ledger (17.0.2.0.0 — replaces the stock-LL flow that
    previously used sca.journal.map).

    Each crypto transaction posted via
    ``sca.transaction.action_inject_to_management_ledger`` consults this
    mapping to find:

      * which management-ledger journal to post to,
      * which asset account (e.g. ``MGT.CRYPTO.USDT``) holds the token,
      * which counterpart account the in/out flow balances against,
      * which res.currency the token amount is denominated in (must
        match the asset account's currency_id when that's set, so the
        per-currency balance constraint on jito.ledger.move holds).
    """

    _name = 'sca.mgt.ledger.map'
    _description = 'Crypto (Address, Token) → Management Ledger Mapping'
    _order = 'watched_address_id, token_symbol'

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
        required=True,
        domain="[('watched_address_id', '=', watched_address_id)]",
        ondelete='cascade',
    )
    token_symbol = fields.Char(
        string='Token Symbol',
        compute='_compute_token_symbol',
        store=True,
        index=True,
    )

    journal_id = fields.Many2one(
        'jito.ledger.journal',
        string='Management Journal',
        required=True,
        help="ML journal the generated jito.ledger.move posts to "
             "(17.0.7.0.0 — switched to jito.ledger.journal). "
             "ledger_id below is computed from it.",
    )
    ledger_id = fields.Many2one(
        related='journal_id.ledger_id',
        store=True,
        readonly=True,
        string='Management Ledger',
    )
    company_id = fields.Many2one(
        related='journal_id.company_id',
        store=True,
        readonly=True,
    )

    # 17.0.8.0.0 — derived from the journal + token. The mapping no
    # longer carries these as standalone editable fields; they're a
    # convenience read-only display sourced from the single source of
    # truth so config can't drift:
    #
    #   asset_account_id     ← journal_id.bank_account_id
    #   counterpart_account_id ← journal_id.suspense_account_id
    #   currency_id          ← token_id.currency_id
    #
    # The pre-migrate to 17.0.8.0.0 backfills the journal + token
    # records from existing mapping values before the DB columns are
    # dropped by Odoo's schema sync.
    asset_account_id = fields.Many2one(
        related='journal_id.bank_account_id',
        string='Crypto Asset Account',
        readonly=True,
        store=False,
        help='Sourced from the Journal\'s Bank/Cash Configuration '
             '(`bank_account_id`). Configure it once on the journal '
             '— it then applies to every mapping that routes through '
             'this journal.',
    )
    counterpart_account_id = fields.Many2one(
        related='journal_id.suspense_account_id',
        string='Counterpart Account',
        readonly=True,
        store=False,
        help='Sourced from the Journal\'s Bank/Cash Configuration '
             '(`suspense_account_id`). Typically a CLR.* suspense '
             'account; inbound crypto txs land here for later '
             'reclassification via Restatement / Regrouping.',
    )
    currency_id = fields.Many2one(
        related='token_id.currency_id',
        string='Token Currency',
        readonly=True,
        store=False,
        help='Sourced from the Watched Token\'s currency. Pick a '
             'preset on the token row to fill it (e.g. USDC preset '
             'sets currency = USDC).',
    )

    _sql_constraints = [
        ('unique_address_token',
         'UNIQUE(watched_address_id, token_symbol)',
         'Each (address, token) pair can have at most one management-'
         'ledger mapping.'),
    ]

    @api.depends('token_id', 'token_id.name')
    def _compute_token_symbol(self):
        for rec in self:
            rec.token_symbol = rec.token_id.name if rec.token_id else False

    # 17.0.7.0.0 — `_compute_ledger` was removed; `ledger_id` is now a
    # plain related field on `journal_id.ledger_id`. The journal's
    # required FK to a ledger means no separate validity check is
    # needed either (`_check_journal_has_ledger` removed below).

    @api.onchange('watched_address_id')
    def _onchange_watched_address_id(self):
        self.token_id = False

    # 17.0.7.0.0 — `_check_journal_has_ledger` was removed; the new
    # `jito.ledger.journal.ledger_id` FK is required, so the related
    # `ledger_id` here can never be False when journal_id is set.

    # 17.0.8.0.0 — `_check_asset_account_currency` removed; the asset
    # account now comes from `journal.bank_account_id` and currency
    # from `token.currency_id`, so any drift between them would
    # require both the journal and the token to be misconfigured — a
    # mapping-level check would catch it too late. The inject action
    # now raises clear errors pointing at the source records instead.

    def name_get(self):
        return [
            (rec.id, '%s / %s → %s' % (
                rec.watched_address_id.name or '',
                rec.token_symbol or '',
                rec.asset_account_id.code or '?',
            ))
            for rec in self
        ]

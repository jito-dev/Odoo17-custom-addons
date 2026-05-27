# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class JitoLedgerJournal(models.Model):
    """Management-ledger-owned journal (17.0.2.0.0).

    Replaces the previous ``account.journal`` + ``jito.ledger.journal.rel``
    pairing (HLD Decision #9 — schema-light). A real ML-owned model
    cleanly separates ML journals from stock LL journals, removes
    cross-domain leakage in Stock Accounting's journal list, and lets
    the ML constraint (`jito.ledger.move.journal_id` in a managed
    ledger) become structural via FK instead of an `@api.constrains`.

    Each row owns:
      * a name + short code (unique per company);
      * a hard FK to its parent ``ledger_id`` (NL or extension);
      * optional currency for single-currency journals;
      * optional default management account (pre-fills new line rows
        on moves posted through this journal);
      * an immutable ``source_account_journal_id`` breadcrumb set by
        the post-migrate when the row was promoted from a legacy
        ``jito.ledger.journal.rel`` entry — downstream migrations use
        it to translate old account.journal IDs to new ones.
    """

    _name = 'jito.ledger.journal'
    _description = 'Management-Ledger Journal'
    _order = 'sequence, code, id'
    _check_company_auto = True

    name = fields.Char(
        string='Name',
        required=True,
        tracking=True,
        help='e.g. "Customer Invoices", "DeFi: Aave Vault".',
    )
    code = fields.Char(
        string='Short Code',
        required=True,
        tracking=True,
        help='Short identifier — convention: CINV / CBILL / CDEFI-AAVE. '
             'Unique within a company.',
    )
    type = fields.Selection(
        selection=[
            ('sale', 'Sales'),
            ('purchase', 'Purchase'),
            ('cash', 'Cash'),
            ('bank', 'Bank'),
            ('general', 'Miscellaneous'),
        ],
        string='Type',
        required=True,
        default='general',
        tracking=True,
        help='Mirrors stock Odoo account.journal.type so management '
             'ledger journals carry the same categorisation '
             '(17.0.2.2.0). Used by the journal picker UX and future '
             'per-type validations (e.g. invoice moves should use '
             'type=sale). Defaults to Miscellaneous when creating a '
             'new journal from inside an NL ledger.',
    )
    ledger_id = fields.Many2one(
        comodel_name='jito.ledger',
        string='Ledger',
        required=True,
        ondelete='restrict',
        index=True,
        tracking=True,
        domain="[('kind', 'in', ['non_leading', 'extension'])]",
        help='Management ledger this journal belongs to. A journal is '
             'owned by exactly one ledger (no rel table needed).',
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        related='ledger_id.company_id',
        store=True,
        readonly=True,
        index=True,
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        tracking=True,
        help='Optional. When set, every move posted through this '
             'journal must use this currency. Leave blank for '
             'multi-currency journals (e.g. a crypto treasury that '
             'receives both USDT and TRX).',
    )
    default_account_id = fields.Many2one(
        comodel_name='jito.ledger.account',
        string='Default Management Account',
        ondelete='restrict',
        tracking=True,
        help='Pre-fills the account_id of new lines on '
             'jito.ledger.move records posted through this journal.',
    )
    active = fields.Boolean(default=True, tracking=True)
    sequence = fields.Integer(default=10)

    # ---- Bank / Cash specific config (17.0.2.2.0 / 17.0.2.2.1) ---------
    # Bank-journal block of stock account.journal, but BOTH the bank
    # account and the suspense account select from the ML chart
    # (jito.ledger.account) — no stock-LL coupling. Visible on the
    # form only when type is bank or cash.

    bank_account_id = fields.Many2one(
        comodel_name='jito.ledger.account',
        string='Bank Account',
        ondelete='restrict',
        copy=False,
        domain="[('company_id', '=', company_id), "
               "('semantic_family', 'in', ['mgt', 'faap'])]",
        help='The ML account that holds this journal\'s balance — '
             'e.g. MGT.CRYPTO.USDT for a TRON treasury wallet, or '
             'FAAP.BANK.EUR for a fiat mirror. Same idea as stock '
             '`account.journal.default_account_id` for bank journals, '
             'but resolved against the management chart of accounts.',
    )
    suspense_account_id = fields.Many2one(
        comodel_name='jito.ledger.account',
        string='Suspense Account',
        ondelete='restrict',
        domain="[('company_id', '=', company_id), "
               "('semantic_family', 'in', ['clr', 'mgt', 'faap'])]",
        help='Where unmatched payments land until reconciliation '
             'classifies them. Mirrors stock '
             '`account.journal.suspense_account_id`. Typically a '
             'CLR.* clearing account. Visible only for Bank/Cash '
             'journals.',
    )

    source_account_journal_id = fields.Many2one(
        comodel_name='account.journal',
        string='Source Stock Journal (legacy)',
        ondelete='set null',
        readonly=True,
        copy=False,
        help='Breadcrumb set by the 17.0.2.0.0 post-migrate when this '
             'row was promoted from a legacy '
             'jito.ledger.journal.rel entry. Downstream module '
             'migrations join on this column to translate old '
             'account.journal FKs to new jito.ledger.journal FKs. '
             'Never written by user.',
    )

    _sql_constraints = [
        (
            'code_company_uniq',
            'UNIQUE(code, company_id)',
            'A management-ledger journal code must be unique within a company.',
        ),
    ]

    @api.constrains('default_account_id', 'ledger_id')
    def _check_default_account(self):
        for rec in self:
            if not rec.default_account_id:
                continue
            if rec.default_account_id.company_id != rec.ledger_id.company_id:
                raise ValidationError(_(
                    "Default account '%s' belongs to company '%s', but "
                    "ledger '%s' belongs to company '%s'.",
                    rec.default_account_id.code,
                    rec.default_account_id.company_id.display_name,
                    rec.ledger_id.display_name,
                    rec.ledger_id.company_id.display_name,
                ))
            if rec.default_account_id.semantic_family == 'grp':
                raise ValidationError(_(
                    "Default account '%s' is a GRP.* (grouping) account "
                    "and is non-posting; it cannot be used as a default "
                    "for journal '%s'.",
                    rec.default_account_id.code,
                    rec.display_name,
                ))

    @api.depends('name', 'code')
    def _compute_display_name(self):
        for rec in self:
            if rec.name and rec.code:
                rec.display_name = '%s (%s)' % (rec.name, rec.code)
            else:
                rec.display_name = rec.name or rec.code or ''

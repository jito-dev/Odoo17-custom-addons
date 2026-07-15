# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class JitoLedgerJournalRel(models.Model):
    """Join model linking jito.ledger to account.journal.

    Implements the journal association without a schema change to
    `account.journal` (per HLD Decision #9). A given account.journal may be
    associated with at most one jito.ledger, enforced by a SQL UNIQUE
    constraint.
    """

    _name = 'jito.ledger.journal.rel'
    _description = 'Ledger / Journal Association'
    _check_company_auto = True

    ledger_id = fields.Many2one(
        comodel_name='jito.ledger',
        string='Ledger',
        required=True,
        ondelete='cascade',
        index=True,
    )
    journal_id = fields.Many2one(
        comodel_name='account.journal',
        string='Journal',
        required=True,
        ondelete='restrict',
        index=True,
    )
    company_id = fields.Many2one(
        related='ledger_id.company_id',
        store=True,
        index=True,
    )

    # Per-journal management-layer config. Independent of stock
    # account.journal.default_account_id (which targets account.account
    # for LL postings). Used by jito_ledger_nl (Phase 2) to pre-fill
    # the account_id of new lines on jito.ledger.move records that post
    # through this journal.
    default_account_id = fields.Many2one(
        comodel_name='jito.ledger.account',
        string='Default Management Account',
        ondelete='restrict',
        tracking=True,
        help="Suggested account when creating new lines in a "
             "jito.ledger.move that posts through this journal. "
             "Independent of the stock account.journal.default_account_id "
             "(which applies to Leading-Ledger postings via account.move).",
    )

    _sql_constraints = [
        (
            'journal_uniq',
            'UNIQUE(journal_id)',
            'A journal can be associated with at most one ledger.',
        ),
    ]

    @api.constrains('ledger_id', 'journal_id')
    def _check_journal_company(self):
        for rel in self:
            if rel.journal_id.company_id != rel.ledger_id.company_id:
                raise ValidationError(_(
                    "Journal '%s' belongs to company '%s', but ledger '%s' belongs to company '%s'.",
                    rel.journal_id.display_name,
                    rel.journal_id.company_id.display_name,
                    rel.ledger_id.display_name,
                    rel.ledger_id.company_id.display_name,
                ))

    @api.constrains('default_account_id', 'ledger_id')
    def _check_default_account(self):
        for rel in self:
            if not rel.default_account_id:
                continue
            if rel.default_account_id.company_id != rel.ledger_id.company_id:
                raise ValidationError(_(
                    "Default account '%s' belongs to company '%s', but ledger "
                    "'%s' belongs to company '%s'.",
                    rel.default_account_id.code,
                    rel.default_account_id.company_id.display_name,
                    rel.ledger_id.display_name,
                    rel.ledger_id.company_id.display_name,
                ))

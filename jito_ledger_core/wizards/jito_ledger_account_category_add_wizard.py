# -*- coding: utf-8 -*-

from odoo import api, fields, models, _


class JitoLedgerAccountCategoryAddWizard(models.TransientModel):
    """Wizard for bulk-assigning existing ``jito.ledger.account`` rows to
    a ``jito.ledger.account.category`` from the category form
    (17.0.3.1.0).

    Odoo's standard One2many "Add a line" creates a *new* record; it
    doesn't let users pick an *existing* one. This wizard fills that
    gap: it surfaces a Many2many tags picker over all accounts NOT
    already in the target category (across every semantic family —
    FAAP / MGT / CLR / GRP — so users can mix FAAP mirrors and NL
    accounts in the same category). On confirm, the wizard sets each
    picked account's ``category_id`` to the target.

    Transient — no data persists after the modal closes.
    """

    _name = 'jito.ledger.account.category.add.wizard'
    _description = 'Add Accounts to Category'

    category_id = fields.Many2one(
        comodel_name='jito.ledger.account.category',
        string='Target Category',
        required=True,
        readonly=True,
    )
    account_ids = fields.Many2many(
        comodel_name='jito.ledger.account',
        string='Accounts to add',
        # Filter: exclude accounts already in this category. Domain
        # deliberately does NOT restrict by semantic_family — the
        # whole point is to let one category span FAAP mirrors AND
        # NL accounts so reports consolidate both sides.
        domain="[('category_id', '!=', category_id), ('active', '=', True)]",
    )

    def action_confirm(self):
        """Assign the picked accounts to the target category and
        close the modal."""
        self.ensure_one()
        if self.account_ids:
            self.account_ids.write({'category_id': self.category_id.id})
        return {'type': 'ir.actions.act_window_close'}

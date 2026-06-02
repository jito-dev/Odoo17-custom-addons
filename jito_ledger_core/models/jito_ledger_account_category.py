# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class JitoLedgerAccountCategory(models.Model):
    """User-defined logical grouping for ``jito.ledger.account`` rows.

    17.0.3.0.0 — added so management reports (Trial Balance, General
    Ledger) can roll up accounts that share a business meaning into a
    single subtotal. Example: a "Sales" category containing
    ``FAAP.Sales_NA`` (FAAP mirror of stock revenue) and ``MGT.Sales``
    (native management revenue account) so the combined report shows
    one Sales row instead of two.

    Categorization is **manual and optional** — see
    `jito.ledger.account.category_id` (`ondelete='set null'`, no
    required). Accounts without a category roll up into the special
    "(Uncategorized)" bucket in reports.

    Flat for v1 (no parent_id). A hierarchy can be added later by
    introducing a Many2one self-reference; existing assignments
    survive.
    """

    _name = 'jito.ledger.account.category'
    _description = 'Management Ledger Account Category'
    _order = 'sequence, name'

    name = fields.Char(
        required=True,
        translate=True,
    )
    sequence = fields.Integer(default=10)
    color = fields.Integer(string='Color Index')
    description = fields.Text()
    active = fields.Boolean(default=True)
    account_ids = fields.One2many(
        comodel_name='jito.ledger.account',
        inverse_name='category_id',
        string='Accounts',
    )
    account_count = fields.Integer(
        string='# Accounts',
        compute='_compute_account_count',
    )

    _sql_constraints = [
        (
            'jito_account_category_name_uniq',
            'UNIQUE(name)',
            'A category with this name already exists.',
        ),
    ]

    @api.depends('account_ids')
    def _compute_account_count(self):
        for record in self:
            record.account_count = len(record.account_ids)

    @api.constrains('name')
    def _check_name_non_empty(self):
        for record in self:
            if not (record.name or '').strip():
                raise ValidationError(_(
                    "Category name cannot be blank."
                ))

    def action_add_accounts(self):
        """Open the "Add existing accounts" wizard (17.0.3.1.0).

        Triggered by the button on the category form. Spans every
        semantic family (FAAP / MGT / CLR / GRP) so one category can
        contain both FAAP mirrors and NL accounts.
        """
        self.ensure_one()
        return {
            'name': _("Add accounts to %s", self.name),
            'type': 'ir.actions.act_window',
            'res_model': 'jito.ledger.account.category.add.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_category_id': self.id},
        }

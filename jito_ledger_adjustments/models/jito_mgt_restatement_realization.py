# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class JitoMgtRestatementRealization(models.Model):
    """One row of the Restatement Realization allocation (17.0.9.0.0).

    When a cross-currency Restatement calibrates its CLR pair on the
    destination's market value (per the 17.0.10.0.0 ADR), the source
    side's LL projection lands at the LL posting rate — leaving a
    residual on the FAAP mirror equal to the company-currency gap
    between the two market translations. That gap is a real economic
    event (conversion fees, slippage, FX loss/gain) and deserves an
    explicit accounting home rather than sitting as an unbalanced
    residual.

    Each row of this model dedicates a slice of that gap to a P&L
    account: e.g. "Conversion Fee 2% → MGT.ConversionFees, 200 USD" +
    "FX Loss → MGT.FXLoss, 800 USD". On Post, every row produces a
    company-currency P&L line on its target account; one consolidated
    counter line on the source's FAAP mirror cancels the residual so
    the FAAP account nets to zero in the LL+NL+EXT combined view.

    Sign convention: ``amount`` is signed in company currency.
    Positive = realized loss (debit expense / credit FAAP).
    Negative = realized gain (credit income / debit FAAP).
    """

    _name = 'jito.mgt.restatement.realization'
    _description = 'Restatement Realization Line (FX Delta Allocation)'
    _order = 'sequence, id'

    restatement_id = fields.Many2one(
        comodel_name='jito.mgt.restatement',
        required=True,
        ondelete='cascade',
        index=True,
    )
    company_id = fields.Many2one(
        related='restatement_id.company_id',
        store=True, readonly=True,
    )
    company_currency_id = fields.Many2one(
        related='restatement_id.company_id.currency_id',
        store=True, readonly=True,
    )
    sequence = fields.Integer(default=10)
    account_id = fields.Many2one(
        comodel_name='jito.ledger.account',
        string='P&L Account',
        required=True,
        domain="[('company_id', '=', company_id), "
               "('account_type', 'in', ["
               "  'expense', 'expense_depreciation', 'expense_direct_cost',"
               "  'income', 'income_other'"
               "])]",
        help="Management-layer P&L account that absorbs this slice of "
             "the FX delta. Typically an expense (e.g. MGT.ConvFees, "
             "MGT.FXLoss) for losses, or income for gains.",
    )
    name = fields.Char(
        string='Description',
        default=lambda self: _("FX realization"),
    )
    amount = fields.Monetary(
        string='Amount',
        currency_field='company_currency_id',
        required=True,
        help="Signed company-currency allocation. Positive = realized "
             "loss (debits expense, credits FAAP residual). Negative "
             "= realized gain (credits income, debits FAAP residual).",
    )

    @api.constrains('amount', 'company_currency_id')
    def _check_amount_non_zero(self):
        for rec in self:
            if rec.company_currency_id and rec.company_currency_id.is_zero(rec.amount):
                raise ValidationError(_(
                    "Realization row %s has a zero amount — remove the "
                    "row or set a non-zero allocation.", rec.name or '?',
                ))

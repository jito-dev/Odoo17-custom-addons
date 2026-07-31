# -*- coding: utf-8 -*-
from odoo import api, fields, models

EXPENSE_TYPES = ('expense', 'expense_direct_cost')

# Longest-prefix-wins mapping of account code -> category code.
#
# Built from the actual chart of accounts (31 expense accounts, verified
# 2026-07-31 on odoo_dev). The overlaps are deliberate and rely on the longest
# match: '6000' is Subcontractor services, but '600000' is the catch-all, and
# '6005'/'6011' are the Upwork/Revolut platform fees that also sit under root 60.
CODE_PREFIX_MAP = {
    # --- root 60: 89.7% of spend, three genuinely different things ----------
    '6000': 'subcontractor',        # 6000 Subcontractor services
    '600000': 'uncategorized',      # 600000 "Expenses" - the catch-all
    '6005': 'platform_fees',        # 600500/600510/600520 Upwork fees
    '6011': 'platform_fees',        # 601100 Revolut FCF service fees
    '500000': 'other',              # Cost of Goods Sold (unused)
    # --- root 61: SaaS ------------------------------------------------------
    '61': 'saas',                   # 6101..6109 AI/Collaboration/Hosting/Sales
    '611000': 'office_fx',          # Purchase of Equipments (not SaaS)
    '612000': 'other',              # Rent
    # --- professional services ---------------------------------------------
    '6200': 'professional',         # Professional fees - tax/accounting
    '6700': 'professional',         # Consulting services
    # --- meals --------------------------------------------------------------
    '6300': 'meals',
    '630000': 'other',              # Salary Expenses
    # --- office + FX --------------------------------------------------------
    '6400': 'office_fx',            # Office equipment & supplies
    '641000': 'office_fx',          # Foreign Exchange Loss
    '642000': 'office_fx',          # Cash Difference Loss
    '443000': 'office_fx',          # Cash Discount Loss
    # --- bank ---------------------------------------------------------------
    '6500': 'bank_fees',            # Bank & FX charges
    '620000': 'bank_fees',          # Bank Fees
    '6790': 'bank_fees',            # Bank Charges
    # --- everything else ----------------------------------------------------
    '6600': 'other',                # Marketing services
    '6800': 'other',                # Recruitment & hiring
    '6900': 'other',                # Training & professional development
    '69000': 'other',               # Disallowable Expenses
    '961000': 'other',              # RD Expenses
    '962000': 'other',              # Sales Expenses
}

FALLBACK_CATEGORY = 'uncategorized'


class AccountAccount(models.Model):
    _inherit = 'account.account'

    expense_category_id = fields.Many2one(
        'jito.expense.category',
        string="Expense Category",
        index=True,
        help="Management category used by the Expenses (Accounting) dashboard. "
             "Set automatically from the account code; override it freely - the "
             "automation never overwrites a value that is already set.",
    )

    # ------------------------------------------------------------------
    # Auto-assignment
    # ------------------------------------------------------------------
    @api.model
    def _jito_category_code_for(self, code):
        """Return the category code for an account code, longest prefix wins."""
        if not code:
            return FALLBACK_CATEGORY
        match = ''
        for prefix in CODE_PREFIX_MAP:
            if code.startswith(prefix) and len(prefix) > len(match):
                match = prefix
        return CODE_PREFIX_MAP.get(match, FALLBACK_CATEGORY)

    @api.model
    def _jito_category_ids_by_code(self):
        categories = self.env['jito.expense.category'].search([])
        return {category.code: category.id for category in categories}

    def _jito_assign_expense_categories(self, force=False):
        """Fill ``expense_category_id`` on expense accounts.

        Never silently drops an account: anything the prefix map does not cover
        lands in *Uncategorized*, which the dashboard shows rather than hides.
        """
        by_code = self._jito_category_ids_by_code()
        if not by_code:
            return
        for account in self:
            if account.account_type not in EXPENSE_TYPES:
                continue
            if account.expense_category_id and not force:
                continue
            target = by_code.get(self._jito_category_code_for(account.code))
            if target and account.expense_category_id.id != target:
                account.expense_category_id = target

    @api.model_create_multi
    def create(self, vals_list):
        accounts = super().create(vals_list)
        accounts._jito_assign_expense_categories()
        return accounts

    def write(self, vals):
        res = super().write(vals)
        # A code or type change can move an account into (or inside) the expense
        # space. Only fills blanks, so a manual override survives.
        if 'code' in vals or 'account_type' in vals:
            self._jito_assign_expense_categories()
        return res

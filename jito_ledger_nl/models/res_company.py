# -*- coding: utf-8 -*-

from odoo import fields, models


class ResCompany(models.Model):
    """Three per-company defaults that drive the NL Customer Invoice
    creation flow (17.0.3.0.0).

    Auto-seeded by jito_ledger_core 17.0.1.6.0's migration; surfaced via
    res.config.settings (Configuration → Customer Invoices) so admins
    can rebind them without touching Developer Mode.
    """

    _inherit = 'res.company'

    jito_default_invoice_journal_id = fields.Many2one(
        comodel_name='account.journal',
        string='Default Customer Invoices Journal',
        domain="[('company_id', '=', id), ('type', '=', 'sale')]",
        help="The journal new Customer Invoices post through. Auto-set "
             "to the seeded 'Customer Invoices' journal on install / "
             "upgrade; admin can rebind via Configuration → Customer "
             "Invoices.",
    )
    jito_default_invoice_income_account_id = fields.Many2one(
        comodel_name='jito.ledger.account',
        string='Default Invoice-Line Income Account',
        domain="[('company_id', '=', id), ('semantic_family', '=', 'mgt')]",
        help="Pre-fill account for invoice product lines. Defaults to "
             "MGT.SALES ('Product Sales').",
    )
    jito_default_invoice_receivable_account_id = fields.Many2one(
        comodel_name='jito.ledger.account',
        string='Default Account Receivable',
        domain="[('company_id', '=', id), ('semantic_family', '=', 'mgt')]",
        help="Account the auto-generated AR balancing line posts to "
             "on Post. Defaults to MGT.RECEIVABLE ('Account Receivable').",
    )

    # ---- Vendor Bill defaults (17.0.4.0.0) -----------------------------------

    jito_default_bill_journal_id = fields.Many2one(
        comodel_name='account.journal',
        string='Default Vendor Bills Journal',
        domain="[('company_id', '=', id), ('type', '=', 'purchase')]",
        help="The journal new Vendor Bills post through. Auto-set to the "
             "seeded 'Vendor Bills' journal (code='CBILL') on install / "
             "upgrade; admin can rebind via Configuration → Vendor Bills.",
    )
    jito_default_bill_expense_account_id = fields.Many2one(
        comodel_name='jito.ledger.account',
        string='Default Bill-Line Expense Account',
        domain="[('company_id', '=', id), ('semantic_family', '=', 'mgt')]",
        help="Pre-fill account for vendor-bill product lines. Defaults to "
             "MGT.EXPENSE ('Operating Expenses').",
    )
    jito_default_bill_payable_account_id = fields.Many2one(
        comodel_name='jito.ledger.account',
        string='Default Account Payable',
        domain="[('company_id', '=', id), ('semantic_family', '=', 'mgt')]",
        help="Account the auto-generated AP balancing line posts to "
             "on Post. Defaults to MGT.PAYABLE ('Account Payable').",
    )

    # ---- Adjustments default (17.0.5.2.0) ------------------------------------

    jito_default_adjustments_journal_id = fields.Many2one(
        comodel_name='account.journal',
        string='Default Adjustments Journal',
        domain="[('company_id', '=', id)]",
        help="Default journal pre-filled by Bridge / Restate / Regroup "
             "wizards. Must be a journal linked to a Non-Leading or "
             "Extension ledger via jito.ledger.journal.rel.",
    )

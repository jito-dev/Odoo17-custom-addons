# -*- coding: utf-8 -*-

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    """Surfaces the three Customer Invoice defaults from res.company on
    a stock Settings → Apps page section (17.0.3.0.0).

    Pattern matches stock Odoo's `account.config.settings` extension:
    each setting is a `related` field on res.company with
    readonly=False, so writing on the wizard updates the underlying
    company.
    """

    _inherit = 'res.config.settings'

    jito_default_invoice_journal_id = fields.Many2one(
        related='company_id.jito_default_invoice_journal_id',
        readonly=False,
        string='Customer Invoices Journal',
    )
    jito_default_invoice_income_account_id = fields.Many2one(
        related='company_id.jito_default_invoice_income_account_id',
        readonly=False,
        string='Invoice-Line Income Account',
    )
    jito_default_invoice_receivable_account_id = fields.Many2one(
        related='company_id.jito_default_invoice_receivable_account_id',
        readonly=False,
        string='Account Receivable',
    )

    # 17.0.4.0.0 — Vendor Bill defaults
    jito_default_bill_journal_id = fields.Many2one(
        related='company_id.jito_default_bill_journal_id',
        readonly=False,
        string='Vendor Bills Journal',
    )
    jito_default_bill_expense_account_id = fields.Many2one(
        related='company_id.jito_default_bill_expense_account_id',
        readonly=False,
        string='Bill-Line Expense Account',
    )
    jito_default_bill_payable_account_id = fields.Many2one(
        related='company_id.jito_default_bill_payable_account_id',
        readonly=False,
        string='Account Payable',
    )

    # 17.0.5.2.0 — Adjustments default
    jito_default_adjustments_journal_id = fields.Many2one(
        related='company_id.jito_default_adjustments_journal_id',
        readonly=False,
        string='Adjustments Journal',
    )

    # 17.0.9.0.0 — Analytic Accounting toggle. Grants the ML-owned
    # analytic group to internal users (mirrors stock's
    # group_analytic_accounting setting), which reveals the Analytic
    # Accounting menus and the analytic_distribution widget/columns.
    group_jito_ledger_analytic = fields.Boolean(
        string='Analytic Accounting',
        implied_group='jito_ledger_nl.group_mgmt_ledger_analytic',
        help="Track analytic distributions on Management Ledger entries "
             "and the FAAP statutory projection. Does not affect stock "
             "Accounting.",
    )

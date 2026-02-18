# -*- coding: utf-8 -*-

from odoo import api, fields, models


class AccountAnalyticLine(models.Model):
    """
    Extend account.analytic.line (timesheets) to link with Billing Runs
    """

    _inherit = 'account.analytic.line'

    # Link to billing run (for traceability)
    tm_billing_run_id = fields.Many2one(
        comodel_name='tm.billing.run',
        string='Billing Run',
        readonly=True,
        index=True,
        help="Billing run that included this timesheet",
    )

    # Link to billing run line (for detailed traceability)
    tm_billing_run_line_ids = fields.Many2many(
        comodel_name='tm.billing.run.line',
        relation='tm_billing_run_line_timesheet_rel',
        column1='timesheet_id',
        column2='billing_line_id',
        string='Billing Lines',
        help="Billing run lines that include this timesheet",
    )

    # Computed status fields for visibility
    is_invoiced = fields.Boolean(
        string='Invoiced',
        compute='_compute_is_invoiced',
        store=True,
        help="True if this timesheet has been included in an invoice",
    )

    invoice_state = fields.Selection(
        related='timesheet_invoice_id.state',
        string='Invoice Status',
        store=True,
        help="Status of the invoice this timesheet is linked to",
    )

    invoice_payment_state = fields.Selection(
        related='timesheet_invoice_id.payment_state',
        string='Payment Status',
        store=True,
        help="Payment status of the invoice",
    )

    @api.depends('timesheet_invoice_id', 'timesheet_invoice_id.state')
    def _compute_is_invoiced(self):
        """Compute if timesheet is invoiced (linked to a non-cancelled invoice)"""
        for line in self:
            line.is_invoiced = bool(
                line.timesheet_invoice_id and
                line.timesheet_invoice_id.state != 'cancel'
            )

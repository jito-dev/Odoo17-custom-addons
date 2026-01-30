# -*- coding: utf-8 -*-

from odoo import fields, models


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

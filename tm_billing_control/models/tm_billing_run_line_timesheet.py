# -*- coding: utf-8 -*-

from odoo import api, fields, models, _


class TmBillingRunLineTimesheet(models.Model):
    """
    Link between billing lines and timesheets with inclusion flag.

    This model enables users to:
    - View individual timesheets within a billing line
    - Include/exclude specific timesheets from invoicing
    - Track which timesheets are billed together
    """

    _name = 'tm.billing.run.line.timesheet'
    _description = 'Billing Line Timesheet Link'
    _order = 'date, timesheet_id'

    # ========================================================================
    # FIELDS
    # ========================================================================

    billing_line_id = fields.Many2one(
        comodel_name='tm.billing.run.line',
        string='Billing Line',
        required=True,
        ondelete='cascade',
        index=True,
    )

    timesheet_id = fields.Many2one(
        comodel_name='account.analytic.line',
        string='Timesheet',
        required=True,
        ondelete='cascade',
        index=True,
    )

    included = fields.Boolean(
        string='Include in Invoice',
        default=True,
        help="Check to include this timesheet in the invoice, uncheck to exclude",
    )

    # Readonly control based on billing run state
    is_readonly = fields.Boolean(
        string='Is Readonly',
        compute='_compute_is_readonly',
        help="True if timesheet link is frozen (invoice created)",
    )

    # ========================================================================
    # RELATED FIELDS FROM TIMESHEET (for easy display)
    # ========================================================================

    @api.depends('billing_line_id.billing_run_id.state')
    def _compute_is_readonly(self):
        """Mark timesheet link as readonly after invoice creation"""
        for line in self:
            line.is_readonly = line.billing_line_id.billing_run_id.state in ('invoiced', 'closed')

    date = fields.Date(
        related='timesheet_id.date',
        string='Date',
        store=True,
        readonly=True,
    )

    employee_id = fields.Many2one(
        comodel_name='hr.employee',
        related='timesheet_id.employee_id',
        string='Employee',
        store=True,
        readonly=True,
    )

    project_id = fields.Many2one(
        comodel_name='project.project',
        related='timesheet_id.project_id',
        string='Project',
        store=True,
        readonly=True,
    )

    task_id = fields.Many2one(
        comodel_name='project.task',
        related='timesheet_id.task_id',
        string='Task',
        store=True,
        readonly=True,
    )

    name = fields.Char(
        related='timesheet_id.name',
        string='Description',
        readonly=True,
    )

    hours = fields.Float(
        related='timesheet_id.unit_amount',
        string='Hours',
        readonly=True,
    )

    rate = fields.Monetary(
        related='timesheet_id.tm_billing_rate',
        string='Rate',
        currency_field='currency_id',
        readonly=True,
    )

    amount = fields.Monetary(
        related='timesheet_id.tm_billable_amount',
        string='Amount',
        currency_field='currency_id',
        readonly=True,
    )

    currency_id = fields.Many2one(
        comodel_name='res.currency',
        related='billing_line_id.currency_id',
        string='Currency',
        readonly=True,
    )

    # ========================================================================
    # CONSTRAINTS
    # ========================================================================

    def write(self, vals):
        """Prevent modifications to timesheet links after invoice creation"""
        from odoo.exceptions import UserError

        # Check if trying to modify the 'included' field
        if 'included' in vals:
            for line in self:
                if line.billing_line_id.billing_run_id.state in ('invoiced', 'closed'):
                    raise UserError(_(
                        'Cannot modify timesheet inclusion after invoice has been created. '
                        'The billing line is frozen once the invoice is generated.'
                    ))
        return super().write(vals)

    def unlink(self):
        """Prevent deletion of timesheet links after invoice creation"""
        from odoo.exceptions import UserError

        for line in self:
            if line.billing_line_id.billing_run_id.state in ('invoiced', 'closed'):
                raise UserError(_(
                    'Cannot remove timesheets from billing line after invoice has been created. '
                    'The billing line is frozen once the invoice is generated.'
                ))
        return super().unlink()

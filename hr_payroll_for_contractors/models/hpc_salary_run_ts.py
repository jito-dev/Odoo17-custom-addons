from odoo import fields, models


class HpcSalaryRunTs(models.Model):
    _name = 'hr.payroll.contractor.salary.ts'
    _description = 'Contractor Salary Run Timesheet Line'
    _order = 'date'

    salary_run_id = fields.Many2one(
        'hr.payroll.contractor.salary.run',
        string='Salary Run',
        required=True,
        ondelete='cascade',
        index=True,
    )
    timesheet_id = fields.Many2one(
        'account.analytic.line',
        string='Timesheet',
        required=True,
        ondelete='cascade',
    )
    include = fields.Boolean(
        string='Include',
        default=True,
    )
    date = fields.Date(
        related='timesheet_id.date',
        string='Date',
        store=True,
        readonly=True,
    )
    project_id = fields.Many2one(
        related='timesheet_id.project_id',
        string='Project',
        store=True,
        readonly=True,
    )
    task_id = fields.Many2one(
        related='timesheet_id.task_id',
        string='Task',
        store=True,
        readonly=True,
    )
    description = fields.Char(
        related='timesheet_id.name',
        string='Description',
        store=True,
        readonly=True,
    )
    hours = fields.Float(
        string='Hours',
        digits=(16, 4),
    )

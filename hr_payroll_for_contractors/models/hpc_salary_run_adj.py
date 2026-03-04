from odoo import fields, models


class HpcSalaryRunAdj(models.Model):
    _name = 'hr.payroll.contractor.salary.adj'
    _description = 'Contractor Salary Run Adjustment'
    _order = 'id'

    salary_run_id = fields.Many2one(
        'hr.payroll.contractor.salary.run',
        string='Salary Run',
        required=True,
        ondelete='cascade',
        index=True,
    )
    description = fields.Char(
        string='Description',
        required=True,
    )
    amount = fields.Float(
        string='Amount',
        required=True,
        help='Positive to add, negative to subtract from total.',
    )
    attachment = fields.Binary(
        string='Attachment',
        attachment=True,
    )
    attachment_filename = fields.Char(
        string='Attachment Filename',
    )
    currency_id = fields.Many2one(
        related='salary_run_id.currency_id',
        string='Currency',
        readonly=True,
    )

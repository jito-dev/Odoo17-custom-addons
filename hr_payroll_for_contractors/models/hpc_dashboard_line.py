from odoo import fields, models


class HpcDashboardLine(models.TransientModel):
    _name = 'hr.payroll.contractor.dashboard.line'
    _description = 'Contractor Payroll Dashboard Line'
    _order = 'employee_id'

    settings_id = fields.Many2one(
        'hr.payroll.contractor.settings',
        string='Settings',
        required=True,
        ondelete='cascade',
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        readonly=True,
    )
    contract_id = fields.Many2one(
        'hr.payroll.contractor.contract',
        string='Contract',
        readonly=True,
    )
    contracting_type = fields.Char(
        string='Contract Type',
        readonly=True,
    )
    total_hours = fields.Float(
        string='Total Hours',
        readonly=True,
    )
    regular_hours = fields.Float(
        string='Hours Worked',
        readonly=True,
    )
    vacation_hours = fields.Float(
        string='Vacation Hours',
        readonly=True,
    )
    sickness_hours = fields.Float(
        string='Sickness Hours',
        readonly=True,
    )
    public_holiday_hours = fields.Float(
        string='Public Holiday Hours',
        readonly=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        readonly=True,
    )
    amount_to_pay = fields.Monetary(
        string='Amount to Pay',
        currency_field='currency_id',
        readonly=True,
    )

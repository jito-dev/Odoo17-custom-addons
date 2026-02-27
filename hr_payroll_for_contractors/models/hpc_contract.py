from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class HpcContract(models.Model):
    _name = 'hr.payroll.contractor.contract'
    _description = 'Contractor Payroll Contract'
    _order = 'employee_id, date_start'

    settings_id = fields.Many2one(
        'hr.payroll.contractor.settings',
        string='Settings',
        required=True,
        ondelete='cascade',
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        index=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        required=True,
        default=lambda self: self.env.company.currency_id,
    )
    date_start = fields.Date(string='Start Date')
    date_end = fields.Date(string='End Date')
    contracting_type = fields.Selection(
        selection=[
            ('hourly', 'Hourly'),
            ('monthly_tracking', 'Monthly with Tracking'),
            ('monthly_fixed', 'Monthly Fixed'),
        ],
        string='Contracting Type',
        required=True,
        default='hourly',
    )
    rate = fields.Monetary(
        string='Hourly Rate',
        currency_field='currency_id',
    )
    monthly_compensation = fields.Monetary(
        string='Monthly Compensation',
        currency_field='currency_id',
    )
    hours_per_day = fields.Float(
        string='Hours per Day',
        default=8.0,
        readonly=True,
    )
    include_overtime = fields.Boolean(
        string='Include Overtime',
        default=False,
        help='For monthly tracking: automatically include overtime hours in salary run computation.',
    )
    display_name = fields.Char(
        string='Display Name',
        compute='_compute_display_name',
        store=True,
    )

    @api.depends('employee_id', 'contracting_type', 'date_start', 'date_end')
    def _compute_display_name(self):
        type_labels = {
            'hourly': 'Hourly',
            'monthly_tracking': 'Monthly Tracking',
            'monthly_fixed': 'Monthly Fixed',
        }
        for contract in self:
            employee = contract.employee_id.name or ''
            ctype = type_labels.get(contract.contracting_type, '')
            start = contract.date_start.strftime('%Y-%m-%d') if contract.date_start else '...'
            end = contract.date_end.strftime('%Y-%m-%d') if contract.date_end else '...'
            contract.display_name = f"{employee} – {ctype} ({start} ~ {end})"

    @api.constrains('employee_id', 'date_start', 'date_end')
    def _check_no_overlap(self):
        for contract in self:
            domain = [
                ('employee_id', '=', contract.employee_id.id),
                ('id', '!=', contract.id),
            ]
            others = self.search(domain)
            for other in others:
                if self._ranges_overlap(
                    contract.date_start, contract.date_end,
                    other.date_start, other.date_end,
                ):
                    raise ValidationError(_(
                        'Contract for employee %s overlaps with an existing contract (%s).',
                        contract.employee_id.name, other.display_name,
                    ))

    @staticmethod
    def _ranges_overlap(start1, end1, start2, end2):
        """Return True if [start1, end1] and [start2, end2] overlap.
        None means open-ended (−∞ or +∞).
        """
        from datetime import date as dt
        _MIN = dt.min
        _MAX = dt.max
        s1 = start1 or _MIN
        e1 = end1 or _MAX
        s2 = start2 or _MIN
        e2 = end2 or _MAX
        return s1 <= e2 and s2 <= e1

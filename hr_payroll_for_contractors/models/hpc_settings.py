from datetime import date
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _


class HpcSettings(models.Model):
    _name = 'hr.payroll.contractor.settings'
    _description = 'Contractor Payroll Settings'
    _order = 'company_id'

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    sickness_task_id = fields.Many2one(
        'project.task',
        string='Sickness Time Off Task Source',
        domain="[('project_id.name', 'ilike', 'Internal')]",
    )
    vacation_task_id = fields.Many2one(
        'project.task',
        string='Paid Time Off / Vacations Source',
        domain="[('project_id.name', 'ilike', 'Internal')]",
    )
    public_holiday_task_id = fields.Many2one(
        'project.task',
        string='Public Holidays Source',
        domain="[('project_id.name', 'ilike', 'Internal')]",
    )
    dashboard_date_start = fields.Date(
        string='Period From',
        default=lambda self: date.today().replace(day=1),
    )
    dashboard_date_end = fields.Date(
        string='Period To',
        default=lambda self: date.today().replace(day=1) + relativedelta(months=1, days=-1),
    )
    contract_ids = fields.One2many(
        'hr.payroll.contractor.contract',
        'settings_id',
        string='Contracts',
    )
    salary_run_ids = fields.One2many(
        'hr.payroll.contractor.salary.run',
        'settings_id',
        string='Salary Runs',
    )
    dashboard_line_ids = fields.One2many(
        'hr.payroll.contractor.dashboard.line',
        'settings_id',
        string='Dashboard Lines',
    )
    dashboard_period_label = fields.Char(
        string='Period',
        compute='_compute_dashboard_period_label',
    )

    @api.depends('dashboard_date_start', 'dashboard_date_end')
    def _compute_dashboard_period_label(self):
        for rec in self:
            start = rec.dashboard_date_start
            end = rec.dashboard_date_end
            if start and end:
                rec.dashboard_period_label = '%s – %s' % (
                    start.strftime('%b %-d, %Y'),
                    end.strftime('%b %-d, %Y'),
                )
            else:
                rec.dashboard_period_label = ''

    @api.model
    def action_open_main(self):
        """Get or create singleton for current company; return form action."""
        company = self.env.company
        # Use sudo so that non-manager roles (e.g. Timesheets Reviewer) can
        # open the dashboard without needing write access on settings.
        sudo_model = self.sudo()
        record = sudo_model.search([('company_id', '=', company.id)], limit=1)
        if not record:
            today = date.today()
            date_start = today.replace(day=1)
            date_end = date_start + relativedelta(months=1, days=-1)
            record = sudo_model.create({
                'company_id': company.id,
                'dashboard_date_start': date_start,
                'dashboard_date_end': date_end,
            })
        # Auto-refresh dashboard lines on every open
        try:
            record.dashboard_line_ids.unlink()
            record._generate_dashboard_lines()
        except Exception:
            pass
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'hr.payroll.contractor.settings',
            'res_id': record.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_previous_month(self):
        self.ensure_one()
        s = self.sudo()
        s.dashboard_date_start = s.dashboard_date_start + relativedelta(months=-1)
        s.dashboard_date_end = s.dashboard_date_start + relativedelta(months=1, days=-1)
        return self.action_refresh_dashboard()

    def action_this_month(self):
        self.ensure_one()
        today = date.today()
        s = self.sudo()
        s.dashboard_date_start = today.replace(day=1)
        s.dashboard_date_end = s.dashboard_date_start + relativedelta(months=1, days=-1)
        return self.action_refresh_dashboard()

    def action_next_month(self):
        self.ensure_one()
        s = self.sudo()
        s.dashboard_date_start = s.dashboard_date_start + relativedelta(months=1)
        s.dashboard_date_end = s.dashboard_date_start + relativedelta(months=1, days=-1)
        return self.action_refresh_dashboard()

    def action_refresh_dashboard(self):
        self.ensure_one()
        s = self.sudo()
        s.dashboard_line_ids.unlink()
        s._generate_dashboard_lines()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'hr.payroll.contractor.settings',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_details(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Dashboard Details'),
            'res_model': 'hr.payroll.contractor.dashboard.line',
            'view_mode': 'pivot,list',
            'domain': [('settings_id', '=', self.id)],
            'target': 'current',
        }

    def action_create_batch_salary_runs(self):
        self.ensure_one()
        wizard = self.env['hr.payroll.contractor.batch.wizard'].create({
            'settings_id': self.id,
            'date_start': self.dashboard_date_start,
            'date_end': self.dashboard_date_end,
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'hr.payroll.contractor.batch.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_new_salary_run(self):
        """Open a blank salary run form pre-linked to this settings."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'hr.payroll.contractor.salary.run',
            'view_mode': 'form',
            'context': {
                'default_settings_id': self.id,
                'default_date_start': self.dashboard_date_start,
                'default_date_end': self.dashboard_date_end,
            },
            'target': 'current',
        }

    @api.model
    def action_open_contracts(self):
        """Open the contracts list for the current company's settings singleton."""
        company = self.env.company
        record = self.search([('company_id', '=', company.id)], limit=1)
        if not record:
            today = date.today()
            date_start = today.replace(day=1)
            date_end = date_start + relativedelta(months=1, days=-1)
            record = self.create({
                'company_id': company.id,
                'dashboard_date_start': date_start,
                'dashboard_date_end': date_end,
            })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Contracts'),
            'res_model': 'hr.payroll.contractor.contract',
            'view_mode': 'tree,form',
            'domain': [('settings_id', '=', record.id)],
            'context': {'default_settings_id': record.id},
            'target': 'current',
        }

    @api.model
    def action_open_config(self):
        """Open the configuration view of the singleton settings form."""
        company = self.env.company
        record = self.search([('company_id', '=', company.id)], limit=1)
        if not record:
            today = date.today()
            date_start = today.replace(day=1)
            date_end = date_start + relativedelta(months=1, days=-1)
            record = self.create({
                'company_id': company.id,
                'dashboard_date_start': date_start,
                'dashboard_date_end': date_end,
            })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'hr.payroll.contractor.settings',
            'res_id': record.id,
            'view_mode': 'form',
            'view_id': self.env.ref(
                'hr_payroll_for_contractors.view_hpc_settings_config_form'
            ).id,
            'target': 'current',
        }

    # -------------------------------------------------------------------------
    # Dashboard generation
    # -------------------------------------------------------------------------

    def _generate_dashboard_lines(self):
        """Find active contracts in the current period and compute per-employee data."""
        self.ensure_one()
        date_start = self.dashboard_date_start
        date_end = self.dashboard_date_end
        if not date_start or not date_end:
            return

        type_labels = {
            'hourly': 'Hourly',
            'monthly_tracking': 'Monthly Tracking',
            'monthly_fixed': 'Monthly Fixed',
        }

        for contract in self.contract_ids:
            # Skip if contract is not active in the period
            if contract.date_end and contract.date_end < date_start:
                continue
            if contract.date_start and contract.date_start > date_end:
                continue

            employee = contract.employee_id
            timesheets = self._get_timesheets(
                employee.id, date_start, date_end
            )

            # Classify hours
            sickness_task = self.sickness_task_id
            vacation_task = self.vacation_task_id
            public_holiday_task = self.public_holiday_task_id

            total_hours = 0.0
            regular_hours = 0.0
            vacation_hours = 0.0
            sickness_hours = 0.0
            public_holiday_hours = 0.0

            for ts in timesheets:
                h = ts.unit_amount
                total_hours += h
                task = ts.task_id
                if sickness_task and task == sickness_task:
                    sickness_hours += h
                elif vacation_task and task == vacation_task:
                    vacation_hours += h
                elif public_holiday_task and task == public_holiday_task:
                    public_holiday_hours += h
                else:
                    regular_hours += h

            amount = self._compute_compensation(
                contract, timesheets, date_start, date_end
            )

            self.env['hr.payroll.contractor.dashboard.line'].create({
                'settings_id': self.id,
                'employee_id': employee.id,
                'contract_id': contract.id,
                'contracting_type': type_labels.get(contract.contracting_type, ''),
                'total_hours': total_hours,
                'regular_hours': regular_hours,
                'vacation_hours': vacation_hours,
                'sickness_hours': sickness_hours,
                'public_holiday_hours': public_holiday_hours,
                'currency_id': contract.currency_id.id,
                'amount_to_pay': amount,
            })

    def _count_working_days(self, date_start, date_end):
        """Count Monday–Friday days in [date_start, date_end]."""
        if not date_start or not date_end:
            return 0
        count = 0
        current = date_start
        while current <= date_end:
            if current.weekday() < 5:  # 0=Mon … 4=Fri
                count += 1
            current += relativedelta(days=1)
        return count

    def _get_timesheets(self, employee_id, date_start, date_end):
        """Return timesheet lines for the employee in the period."""
        domain = [
            ('employee_id', '=', employee_id),
            ('date', '>=', date_start),
            ('date', '<=', date_end),
            ('project_id', '!=', False),
        ]
        return self.env['account.analytic.line'].search(domain)

    def _compute_compensation(self, contract, timesheets, date_start, date_end):
        """Compute compensation for a contract given the timesheets in period."""
        ctype = contract.contracting_type

        if ctype == 'hourly':
            special_task_ids = set(filter(None, [
                self.sickness_task_id.id,
                self.vacation_task_id.id,
                self.public_holiday_task_id.id,
            ]))
            regular_hours = sum(
                ts.unit_amount for ts in timesheets
                if ts.task_id.id not in special_task_ids
            )
            return regular_hours * contract.rate

        elif ctype == 'monthly_tracking':
            expected_hours = self._count_working_days(date_start, date_end) * 8
            if expected_hours <= 0:
                return 0.0
            tracked_hours = sum(timesheets.mapped('unit_amount'))
            fulfillment = tracked_hours / expected_hours
            if fulfillment > 1.0 and not contract.include_overtime:
                fulfillment = 1.0
            return fulfillment * contract.monthly_compensation

        elif ctype == 'monthly_fixed':
            return contract.monthly_compensation

        return 0.0

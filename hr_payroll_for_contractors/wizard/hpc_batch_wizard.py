from odoo import api, fields, models, _


class HpcBatchWizard(models.TransientModel):
    _name = 'hr.payroll.contractor.batch.wizard'
    _description = 'Contractor Payroll Batch Salary Run Wizard'

    settings_id = fields.Many2one(
        'hr.payroll.contractor.settings',
        string='Settings',
        required=True,
    )
    date_start = fields.Date(string='Date From', required=True)
    date_end = fields.Date(string='Date To', required=True)
    line_ids = fields.One2many(
        'hr.payroll.contractor.batch.wizard.line',
        'wizard_id',
        string='Preview Lines',
    )

    @api.model_create_multi
    def create(self, vals_list):
        wizards = super().create(vals_list)
        for wizard in wizards:
            wizard._build_preview_lines()
        return wizards

    def _build_preview_lines(self):
        self.ensure_one()
        settings = self.settings_id
        date_start = self.date_start
        date_end = self.date_end

        type_labels = {
            'hourly': 'Hourly',
            'monthly_tracking': 'Monthly Tracking',
            'monthly_fixed': 'Monthly Fixed',
        }

        lines = []
        for contract in settings.contract_ids:
            # Skip if contract not active in period
            if contract.date_end and contract.date_end < date_start:
                continue
            if contract.date_start and contract.date_start > date_end:
                continue

            employee = contract.employee_id
            timesheets = settings._get_timesheets(
                employee.id, date_start, date_end
            )
            total_hours = sum(timesheets.mapped('unit_amount'))
            amount = settings._compute_compensation(
                contract, timesheets, date_start, date_end
            )

            # Check for existing salary run
            existing_run = self.env['hr.payroll.contractor.salary.run'].search([
                ('settings_id', '=', settings.id),
                ('employee_id', '=', employee.id),
                ('date_start', '=', date_start),
                ('date_end', '=', date_end),
                ('contract_id', '=', contract.id),
            ], limit=1)

            lines.append({
                'wizard_id': self.id,
                'employee_id': employee.id,
                'contract_id': contract.id,
                'contracting_type': type_labels.get(contract.contracting_type, ''),
                'selected': True,
                'total_hours': total_hours,
                'currency_id': contract.currency_id.id,
                'amount_to_pay': amount,
                'existing_run_id': existing_run.id if existing_run else False,
            })

        if lines:
            self.env['hr.payroll.contractor.batch.wizard.line'].create(lines)

    def action_create_all_selected(self):
        """Create salary runs for all selected lines."""
        created = 0
        for line in self.line_ids.filtered(lambda l: l.selected):
            if not line.existing_run_id:
                line._create_salary_run()
                created += 1
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Done'),
                'message': _('%d salary run(s) created.') % created,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }


class HpcBatchWizardLine(models.TransientModel):
    _name = 'hr.payroll.contractor.batch.wizard.line'
    _description = 'Contractor Payroll Batch Wizard Line'
    _order = 'employee_id'

    wizard_id = fields.Many2one(
        'hr.payroll.contractor.batch.wizard',
        string='Wizard',
        required=True,
        ondelete='cascade',
    )
    employee_id = fields.Many2one('hr.employee', string='Employee', readonly=True)
    contract_id = fields.Many2one(
        'hr.payroll.contractor.contract',
        string='Contract',
        readonly=True,
    )
    contracting_type = fields.Char(string='Contract Type', readonly=True)
    selected = fields.Boolean(string='Selected', default=True)
    total_hours = fields.Float(string='Total Hours', readonly=True)
    currency_id = fields.Many2one('res.currency', string='Currency', readonly=True)
    amount_to_pay = fields.Monetary(
        string='Amount to Pay',
        currency_field='currency_id',
        readonly=True,
    )
    existing_run_id = fields.Many2one(
        'hr.payroll.contractor.salary.run',
        string='Existing Run',
        readonly=True,
    )

    def action_create_single_run(self):
        """Create salary run and open it in the main view."""
        self.ensure_one()
        if self.existing_run_id:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Skipped'),
                    'message': _('A salary run already exists for %s in this period.') % self.employee_id.name,
                    'type': 'warning',
                    'sticky': False,
                },
            }
        run = self._create_salary_run()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'hr.payroll.contractor.salary.run',
            'res_id': run.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
        }

    def _create_salary_run(self):
        """Internal: create and return the salary run record."""
        wizard = self.wizard_id
        run = self.env['hr.payroll.contractor.salary.run'].create({
            'settings_id': wizard.settings_id.id,
            'contract_id': self.contract_id.id,
            'date_start': wizard.date_start,
            'date_end': wizard.date_end,
        })
        # Trigger compute
        run.action_compute()
        # Update existing_run_id to reflect newly created run
        self.existing_run_id = run
        return run

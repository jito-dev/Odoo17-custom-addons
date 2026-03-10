from datetime import date
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError


class HpcSalaryRun(models.Model):
    _name = 'hr.payroll.contractor.salary.run'
    _description = 'Contractor Salary Run'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_start desc, id desc'

    _sql_constraints = [
        (
            'unique_run',
            'UNIQUE(settings_id, employee_id, date_start, date_end, contract_id)',
            'A salary run already exists for this employee with the same period and contract.',
        ),
    ]

    reference = fields.Char(
        string='Reference',
        default=lambda self: _('New'),
        readonly=True,
        index=True,
        copy=False,
    )
    settings_id = fields.Many2one(
        'hr.payroll.contractor.settings',
        string='Settings',
        required=True,
        ondelete='restrict',
    )
    contract_id = fields.Many2one(
        'hr.payroll.contractor.contract',
        string='Contract',
        required=True,
    )
    employee_id = fields.Many2one(
        related='contract_id.employee_id',
        string='Employee',
        store=True,
        readonly=True,
    )
    contract_type = fields.Char(
        string='Contract Type',
        compute='_compute_contract_type',
        store=True,
        readonly=True,
    )
    currency_id = fields.Many2one(
        related='contract_id.currency_id',
        string='Currency',
        store=True,
        readonly=True,
    )
    date_start = fields.Date(
        string='Date From',
        required=True,
        default=lambda self: date.today().replace(day=1),
    )
    date_end = fields.Date(
        string='Date To',
        required=True,
        default=lambda self: date.today().replace(day=1) + relativedelta(months=1, days=-1),
    )
    include_overtime = fields.Boolean(
        string='Include Overtime',
        default=False,
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('approved_and_locked', 'Approved & Locked'),
            ('invoiced', 'Invoiced'),
        ],
        string='Status',
        default='draft',
        tracking=True,
    )
    timesheet_line_ids = fields.One2many(
        'hr.payroll.contractor.salary.ts',
        'salary_run_id',
        string='Timesheet Lines',
    )
    adjustment_ids = fields.One2many(
        'hr.payroll.contractor.salary.adj',
        'salary_run_id',
        string='Adjustments',
    )
    invoice_id = fields.Many2one(
        'account.move',
        string='Vendor Bill',
        readonly=True,
        copy=False,
    )
    contractor_invoice_file = fields.Binary(
        string='Contractor Invoice',
        attachment=True,
        copy=False,
        help='Optional contractor-issued invoice file. When a Vendor Bill is created from '
             'this salary run the file will be automatically attached to it.',
    )
    contractor_invoice_filename = fields.Char(
        string='Contractor Invoice Filename',
        copy=False,
    )
    total_hours = fields.Float(
        string='Total Hours',
        compute='_compute_totals',
        store=True,
    )
    calculated_compensation = fields.Monetary(
        string='Calculated Compensation',
        currency_field='currency_id',
        compute='_compute_totals',
        store=True,
    )
    total_adjustments = fields.Monetary(
        string='Total Adjustments',
        currency_field='currency_id',
        compute='_compute_adjustments',
        store=True,
    )
    total_to_pay = fields.Monetary(
        string='Total to Pay',
        currency_field='currency_id',
        compute='_compute_total_to_pay',
        store=True,
    )
    expected_hours = fields.Float(
        string='Expected Hours',
        compute='_compute_overtime_info',
        help='Expected working hours for the period (working days × 8 h/day). '
             'Only relevant for Monthly Tracking contracts.',
    )
    overtime_hours = fields.Float(
        string='Overtime Hours',
        compute='_compute_overtime_info',
        help='Hours worked above the expected hours for the period.',
    )
    contract_rate = fields.Monetary(
        string='Hourly Rate',
        related='contract_id.rate',
        currency_field='currency_id',
        readonly=True,
    )
    contract_monthly_compensation = fields.Monetary(
        string='Monthly Compensation',
        related='contract_id.monthly_compensation',
        currency_field='currency_id',
        readonly=True,
    )
    contract_state = fields.Selection(
        related='contract_id.state',
        string='Contract Status',
    )
    hours_fulfillment = fields.Float(
        string='Fulfillment',
        compute='_compute_hours_fulfillment',
        store=True,
        digits=(5, 4),
        help='Ratio of tracked hours to expected hours (e.g. 0.99 = 99%). '
             'Only meaningful for Monthly Tracking contracts.',
    )
    employee_confirmation = fields.Selection([
        ('waiting', 'Waiting Employee Confirmation'),
        ('confirmed', 'Confirmed by Employee'),
    ], string='Employee Confirmation', default='waiting', tracking=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if 'settings_id' in fields_list and not res.get('settings_id'):
            settings = self.env['hr.payroll.contractor.settings'].search(
                [('company_id', '=', self.env.company.id)], limit=1
            )
            if settings:
                res['settings_id'] = settings.id
        return res

    @api.onchange('contract_id')
    def _onchange_contract_id(self):
        if self.contract_id:
            self.include_overtime = self.contract_id.include_overtime

    @api.constrains('date_start', 'date_end', 'contract_id')
    def _check_monthly_period(self):
        for run in self:
            if run.state != 'draft':
                continue
            if not run.contract_id:
                continue
            ctype = run.contract_id.contracting_type
            if ctype not in ('monthly_tracking', 'monthly_fixed'):
                continue
            if not run.date_start or not run.date_end:
                continue
            if run.date_start.day != 1:
                raise ValidationError(_(
                    'For monthly contracts, Date From must be the 1st day of a month.'
                ))
            expected_end = run.date_start + relativedelta(months=1, days=-1)
            if run.date_end != expected_end:
                raise ValidationError(_(
                    'For monthly contracts, Date To must be the last day of the same month.'
                ))

    @api.depends('contract_id.contracting_type')
    def _compute_contract_type(self):
        type_labels = {
            'hourly': 'Hourly',
            'monthly_tracking': 'Monthly Tracking',
            'monthly_fixed': 'Monthly Fixed',
        }
        for run in self:
            run.contract_type = type_labels.get(
                run.contract_id.contracting_type, ''
            ) if run.contract_id else ''

    @api.depends(
        'timesheet_line_ids.include',
        'timesheet_line_ids.hours',
        'contract_id',
        'date_start',
        'date_end',
        'include_overtime',
    )
    def _compute_totals(self):
        for run in self:
            included = run.timesheet_line_ids.filtered(lambda t: t.include)
            run.total_hours = sum(included.mapped('hours'))
            run.calculated_compensation = run._compute_calculated_compensation()

    @api.depends('adjustment_ids.amount')
    def _compute_adjustments(self):
        for run in self:
            run.total_adjustments = sum(run.adjustment_ids.mapped('amount'))

    @api.depends('calculated_compensation', 'total_adjustments')
    def _compute_total_to_pay(self):
        for run in self:
            run.total_to_pay = run.calculated_compensation + run.total_adjustments

    @api.depends(
        'contract_id',
        'date_start',
        'date_end',
        'timesheet_line_ids.include',
        'timesheet_line_ids.hours',
    )
    def _compute_overtime_info(self):
        for run in self:
            if (
                not run.contract_id
                or run.contract_id.contracting_type != 'monthly_tracking'
                or not run.date_start
                or not run.date_end
            ):
                run.expected_hours = 0.0
                run.overtime_hours = 0.0
                continue
            expected = run.settings_id._count_working_days(
                run.date_start, run.date_end
            ) * 8
            run.expected_hours = expected
            included = run.timesheet_line_ids.filtered(lambda t: t.include)
            tracked = sum(included.mapped('hours'))
            run.overtime_hours = max(0.0, tracked - expected)

    @api.depends(
        'timesheet_line_ids.include',
        'timesheet_line_ids.hours',
        'contract_id.contracting_type',
        'date_start',
        'date_end',
    )
    def _compute_hours_fulfillment(self):
        for run in self:
            if (
                run.contract_id
                and run.contract_id.contracting_type == 'monthly_tracking'
                and run.date_start
                and run.date_end
                and run.settings_id
            ):
                expected = run.settings_id._count_working_days(
                    run.date_start, run.date_end
                ) * 8
                if expected > 0:
                    included = run.timesheet_line_ids.filtered(lambda t: t.include)
                    tracked = sum(included.mapped('hours'))
                    run.hours_fulfillment = tracked / expected
                    continue
            run.hours_fulfillment = 0.0

    def _compute_calculated_compensation(self):
        """Compute compensation based on contract type."""
        self.ensure_one()
        contract = self.contract_id
        if not contract:
            return 0.0

        ctype = contract.contracting_type
        settings = self.settings_id

        if ctype == 'hourly':
            # Sum hours excluding sickness, vacation, public holiday tasks
            special_task_ids = set(filter(None, [
                settings.sickness_task_id.id,
                settings.vacation_task_id.id,
                settings.public_holiday_task_id.id,
            ]))
            included = self.timesheet_line_ids.filtered(lambda t: t.include)
            regular_hours = sum(
                t.hours for t in included
                if t.task_id.id not in special_task_ids
            )
            return regular_hours * contract.rate

        elif ctype == 'monthly_tracking':
            # Only works for full-month periods
            if not (self.date_start and self.date_end):
                return 0.0
            expected_hours = settings._count_working_days(self.date_start, self.date_end) * 8
            if expected_hours <= 0:
                return 0.0
            included = self.timesheet_line_ids.filtered(lambda t: t.include)
            tracked_hours = sum(included.mapped('hours'))
            fulfillment = tracked_hours / expected_hours
            if fulfillment > 1.0 and not self.include_overtime:
                fulfillment = 1.0
            return fulfillment * contract.monthly_compensation

        elif ctype == 'monthly_fixed':
            return contract.monthly_compensation

        return 0.0

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('reference', _('New')) == _('New'):
                vals['reference'] = self.env['ir.sequence'].next_by_code(
                    'hr.payroll.contractor.salary.run'
                ) or _('New')
            # Initialize include_overtime from contract default (can be overridden later)
            if 'include_overtime' not in vals and vals.get('contract_id'):
                contract = self.env['hr.payroll.contractor.contract'].browse(
                    vals['contract_id']
                )
                vals['include_overtime'] = contract.include_overtime
        return super().create(vals_list)

    def _do_compute(self):
        """Core compute: fetch timesheets and recreate timesheet_line_ids. Returns line count."""
        self.ensure_one()
        timesheets = self.settings_id._get_timesheets(
            self.employee_id.id, self.date_start, self.date_end
        )
        self.timesheet_line_ids.unlink()
        lines = [
            {
                'salary_run_id': self.id,
                'timesheet_id': ts.id,
                'include': True,
                'hours': ts.unit_amount,
            }
            for ts in timesheets
        ]
        if lines:
            self.env['hr.payroll.contractor.salary.ts'].create(lines)
        return len(lines)

    def action_compute(self):
        """Fetch timesheets, recreate timesheet_line_ids."""
        self.ensure_one()
        if self.state in ('approved_and_locked', 'invoiced'):
            raise UserError(_('Cannot recompute a locked or invoiced salary run.'))
        count = self._do_compute()
        self.write({'employee_confirmation': 'waiting'})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Computed'),
                'message': _('Timesheet lines computed: %d lines loaded.') % count,
                'type': 'success',
                'sticky': False,
                'next': {
                    'type': 'ir.actions.act_window',
                    'res_model': 'hr.payroll.contractor.salary.run',
                    'res_id': self.id,
                    'view_mode': 'form',
                    'views': [(False, 'form')],
                    'target': 'current',
                },
            },
        }

    def action_batch_compute(self):
        """Recompute timesheets for all selected draft salary runs."""
        computed = 0
        skipped = 0
        errors = []
        for run in self:
            if run.state in ('approved_and_locked', 'invoiced'):
                skipped += 1
                continue
            try:
                run._do_compute()
                computed += 1
            except Exception as e:
                errors.append('%s: %s' % (run.reference, e))
        msg = _('%d salary run(s) recomputed.') % computed
        if skipped:
            msg += ' ' + _('%d skipped (locked/invoiced).') % skipped
        if errors:
            msg += '\n' + '\n'.join(errors)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Batch Recompute'),
                'message': msg,
                'type': 'warning' if errors else 'success',
                'sticky': bool(errors),
            },
        }

    def action_batch_approve(self):
        """Approve all selected draft salary runs."""
        approved = 0
        skipped = 0
        for run in self:
            if run.state != 'draft':
                skipped += 1
                continue
            run.state = 'approved_and_locked'
            approved += 1
        msg = _('%d salary run(s) approved.') % approved
        if skipped:
            msg += ' ' + _('%d skipped (not in draft state).') % skipped
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Batch Approve'),
                'message': msg,
                'type': 'success',
                'sticky': False,
            },
        }

    def action_approve(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('Only draft salary runs can be approved.'))
        self.state = 'approved_and_locked'

    def action_unlock(self):
        self.ensure_one()
        if self.state != 'approved_and_locked':
            raise UserError(_('Only approved salary runs can be unlocked.'))
        if self.invoice_id:
            raise UserError(_('Cannot unlock a salary run that already has an invoice.'))
        self.write({'state': 'draft', 'employee_confirmation': 'waiting'})

    def action_create_invoice(self):
        """Create vendor bill from this salary run."""
        self.ensure_one()
        if self.state != 'approved_and_locked':
            raise UserError(_('Only approved salary runs can be invoiced.'))
        if self.invoice_id:
            raise UserError(_('This salary run already has an invoice.'))

        employee = self.employee_id
        partner = employee.work_contact_id
        if not partner:
            raise UserError(_(
                'Employee %s has no work contact set. Please configure it first.',
                employee.name,
            ))

        # Build invoice lines
        invoice_lines = []

        # Main compensation line
        invoice_lines.append((0, 0, {
            'name': _('%s – %s – %s to %s') % (
                self.reference,
                self.contract_type,
                self.date_start,
                self.date_end,
            ),
            'quantity': 1,
            'price_unit': self.calculated_compensation,
        }))

        # Adjustment lines
        for adj in self.adjustment_ids:
            invoice_lines.append((0, 0, {
                'name': adj.description,
                'quantity': 1,
                'price_unit': adj.amount,
            }))

        invoice = self.env['account.move'].create({
            'move_type': 'in_invoice',
            'partner_id': partner.id,
            'currency_id': self.currency_id.id,
            'invoice_date': fields.Date.today(),
            'invoice_line_ids': invoice_lines,
            'narration': _('Salary run %s') % self.reference,
        })

        self.invoice_id = invoice
        self.state = 'invoiced'

        # Attach the contractor invoice file to the vendor bill (if uploaded)
        if self.contractor_invoice_file:
            self.env['ir.attachment'].create({
                'name': self.contractor_invoice_filename or 'contractor_invoice',
                'type': 'binary',
                'datas': self.with_context(bin_size=False).contractor_invoice_file,
                'res_model': 'account.move',
                'res_id': invoice.id,
            })

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': invoice.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_confirm_compensation(self):
        """Employee acknowledges and confirms their expected compensation amount."""
        self.ensure_one()
        if (self.env.user != self.employee_id.user_id
                and not self.env.user.has_group(
                    'hr_payroll_for_contractors.group_hpc_user')):
            raise UserError(_("You can only confirm your own salary runs."))
        self.sudo().write({'employee_confirmation': 'confirmed'})

    def action_unconfirm_compensation(self):
        """Employee retracts their confirmation, resetting to waiting."""
        self.ensure_one()
        if (self.env.user != self.employee_id.user_id
                and not self.env.user.has_group(
                    'hr_payroll_for_contractors.group_hpc_user')):
            raise UserError(_("You can only unconfirm your own salary runs."))
        self.sudo().write({'employee_confirmation': 'waiting'})

    def action_open_form(self):
        """Open this salary run in full-page form (used from embedded list)."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'hr.payroll.contractor.salary.run',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_open_bill(self):
        """Open the vendor bill linked to this salary run."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': self.invoice_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_open_contract(self):
        """Open the contract linked to this salary run."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'hr.payroll.contractor.contract',
            'res_id': self.contract_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_period_prev_month(self):
        self.ensure_one()
        start = date.today().replace(day=1) - relativedelta(months=1)
        self.date_start = start
        self.date_end = start + relativedelta(months=1, days=-1)

    def action_period_this_month(self):
        self.ensure_one()
        start = date.today().replace(day=1)
        self.date_start = start
        self.date_end = start + relativedelta(months=1, days=-1)

    def action_period_next_month(self):
        self.ensure_one()
        start = date.today().replace(day=1) + relativedelta(months=1)
        self.date_start = start
        self.date_end = start + relativedelta(months=1, days=-1)

    def unlink(self):
        for run in self:
            if run.invoice_id:
                raise UserError(_(
                    'Cannot delete salary run "%s" because it has a linked vendor bill. '
                    'Delete the vendor bill first.',
                    run.reference,
                ))
        return super().unlink()

    def write(self, vals):
        # Employees (group_hpc_employee without group_hpc_user) may only write
        # adjustment_ids on their own salary runs. All other field changes are blocked.
        if (not self.env.su
                and self.env.user.has_group('hr_payroll_for_contractors.group_hpc_employee')
                and not self.env.user.has_group('hr_payroll_for_contractors.group_hpc_user')):
            employee_allowed_fields = {'adjustment_ids'}
            disallowed = set(vals.keys()) - employee_allowed_fields
            if disallowed:
                raise AccessError(_(
                    'You are not allowed to modify salary run fields: %s.',
                    ', '.join(sorted(disallowed)),
                ))

        for run in self:
            if run.state == 'approved_and_locked' and any(
                k in vals for k in ['contract_id', 'date_start', 'date_end']
            ):
                raise ValidationError(_(
                    'Cannot modify core fields of an approved salary run. Unlock it first.'
                ))
            if run.state == 'invoiced':
                protected = {'contract_id', 'date_start', 'date_end', 'include_overtime',
                             'adjustment_ids'}
                if set(vals.keys()) & protected:
                    raise ValidationError(_(
                        'Cannot modify an invoiced salary run.'
                    ))
        return super().write(vals)

import json
from datetime import date, datetime
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
    invoice_payment_state = fields.Selection(
        related='invoice_id.payment_state',
        string='Bill Payment Status',
        store=True,
        readonly=True,
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
            run.total_hours = round(sum(included.mapped('hours')), 2)
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
            tracked = round(sum(included.mapped('hours')), 2)
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
                    tracked = round(sum(included.mapped('hours')), 2)
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
            regular_hours = round(sum(
                t.hours for t in included
                if t.task_id.id not in special_task_ids
            ), 2)
            return regular_hours * contract.rate

        elif ctype == 'monthly_tracking':
            # Only works for full-month periods
            if not (self.date_start and self.date_end):
                return 0.0
            expected_hours = settings._count_working_days(self.date_start, self.date_end) * 8
            if expected_hours <= 0:
                return 0.0
            included = self.timesheet_line_ids.filtered(lambda t: t.include)
            tracked_hours = round(sum(included.mapped('hours')), 2)
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
        """Core compute: fetch timesheets and recreate timesheet_line_ids. Returns line count.

        Uses sudo() internally for timesheet line operations so any role
        (manager, ts_reviewer, employee) can trigger a recompute without
        needing direct write/delete access on salary.ts records.
        """
        self.ensure_one()
        timesheets = self.settings_id.sudo()._get_timesheets(
            self.employee_id.id, self.date_start, self.date_end
        )
        self.sudo().timesheet_line_ids.unlink()
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
            self.env['hr.payroll.contractor.salary.ts'].sudo().create(lines)
        return len(lines)

    def action_compute(self):
        """Fetch timesheets, recreate timesheet_line_ids."""
        self.ensure_one()
        if self.state in ('approved_and_locked', 'invoiced'):
            raise UserError(_('Cannot recompute a locked or invoiced salary run.'))
        count = self._do_compute()
        self.sudo().write({'employee_confirmation': 'waiting'})
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

    def action_employee_recompute(self):
        """Allow employees to recompute their own draft salary runs."""
        self.ensure_one()
        if self.state in ('approved_and_locked', 'invoiced'):
            raise UserError(_('Cannot recompute a locked or invoiced salary run.'))
        # Verify the current user owns this salary run
        if self.employee_id.user_id != self.env.user:
            raise AccessError(_('You can only recompute your own salary runs.'))
        count = self._do_compute()
        self.sudo().write({'employee_confirmation': 'waiting'})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Recomputed'),
                'message': _('Timesheet lines recomputed: %d lines loaded.') % count,
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
                'title': _('Recompute Salary Runs'),
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

    def _is_crypto_payment(self):
        """True when the contract's selected payment method is crypto (no bill)."""
        self.ensure_one()
        pm = self.contract_id.payment_method_id if self.contract_id else False
        return bool(pm and pm.method_type == 'crypto')

    def _create_vendor_bill(self):
        """Create the vendor bill from this salary run's FINAL invoice numbers as a
        single consolidated line (adjustments are already folded into the total, so
        no separate base/adjustment postings). The contractor PDF is attached for
        reference WITHOUT AI/OCR digitization. Returns the created account.move."""
        self.ensure_one()
        if self.state != 'approved_and_locked':
            raise UserError(_('Only approved salary runs can be invoiced.'))
        if self.invoice_id:
            raise UserError(_('This salary run already has an invoice.'))

        # Crypto payees are paid/booked outside this flow — no vendor bill.
        if self._is_crypto_payment():
            raise UserError(_(
                'Payment method is crypto — vendor bill creation is skipped for %s.',
                self.reference))

        # Ensure a fully-populated vendor partner (+ recipient bank), built from the
        # contract's legal entity + selected payment method — NO service agreement
        # required (the data lives on the contract).
        contract = self.contract_id
        if not contract:
            raise UserError(_('This salary run has no contract — cannot determine the vendor.'))
        partner, partner_bank = contract._ensure_payroll_vendor()
        sa = contract.service_agreement_id  # optional; used below for rate / due date

        # Resolve contractor invoice data for references, dates and final numbers
        inv_field = self._fields.get('contractor_invoice_ids')
        inv = self.contractor_invoice_ids[:1] if inv_field else None
        inv_uid = (inv.invoice_uid if inv and inv.invoice_uid else None) or self.reference
        inv_date = self.date_end.strftime('%d %B %Y') if self.date_end else ''

        # Extract invoice_date from contractor invoice context (dd.mm.yyyy)
        bill_date = None
        if inv and inv.context_data:
            try:
                ctx = json.loads(inv.context_data)
                ctx_invoice_date = ctx.get('ctx', {}).get('invoice_date', '')
                if ctx_invoice_date:
                    bill_date = datetime.strptime(ctx_invoice_date, '%d.%m.%Y').date()
            except (json.JSONDecodeError, ValueError):
                pass

        # ── Single consolidated line that mirrors the contractor's issued invoice.
        # amount_on_invoice already == total_to_pay (base compensation + adjustments).
        line_name = _('%s – %s to %s – inv %s') % (
            self.contract_type, self.date_start, self.date_end, inv_uid)
        rate = sa.hourly_rate if sa else 0.0
        if inv and inv.amount_on_invoice:
            amount = inv.amount_on_invoice
            hours = inv.hours_on_invoice
            if hours and rate and abs(hours * rate - amount) <= 0.01:
                line_vals = {'name': line_name, 'quantity': hours, 'price_unit': rate}
            else:
                line_vals = {'name': line_name, 'quantity': 1, 'price_unit': amount}
        else:
            # No contractor invoice / non-hourly → one consolidated total line.
            line_vals = {'name': line_name, 'quantity': 1, 'price_unit': self.total_to_pay}

        # Route the expense to the configured payroll account, else the dedicated
        # '6000 Subcontractor services' account (get-or-created here on demand).
        expense_account = self.settings_id._resolve_payroll_expense_account() if self.settings_id else False
        if expense_account:
            line_vals['account_id'] = expense_account.id

        invoice_vals = {
            'move_type': 'in_invoice',
            'currency_id': self.currency_id.id,
            'invoice_date': bill_date or self.date_end,
            'invoice_line_ids': [(0, 0, line_vals)],
            'narration': _('Salary run %s') % self.reference,
            'ref': inv_uid,
            'payment_reference': 'Payment for invoice %s from %s' % (inv_uid, inv_date),
            'salary_run_id': self.id,
        }
        if partner:
            invoice_vals['partner_id'] = partner.id

        invoice = self.env['account.move'].create(invoice_vals)

        # Recipient bank = the selected payment method's account (no OCR guesswork)
        if partner_bank:
            invoice.partner_bank_id = partner_bank.id

        # Set due date: bill_date + payment_banking_days (business days)
        actual_bill_date = bill_date or self.date_end
        banking_days = sa.payment_banking_days if sa else 0
        if actual_bill_date and banking_days:
            due = actual_bill_date
            days_added = 0
            while days_added < banking_days:
                due += relativedelta(days=1)
                if due.weekday() < 5:  # Mon–Fri
                    days_added += 1
            invoice.invoice_date_due = due

        self.invoice_id = invoice
        self.state = 'invoiced'

        # Attach the contractor invoice PDF for reference — skip AI/OCR digitization
        # (build from data, not by reading the PDF). Mirrors the Upwork bill pattern.
        if self.contractor_invoice_file:
            att = self.env['ir.attachment'].create({
                'name': self.contractor_invoice_filename or 'contractor_invoice.pdf',
                'type': 'binary',
                'datas': self.with_context(bin_size=False).contractor_invoice_file,
                'mimetype': 'application/pdf',
                'res_model': 'account.move',
                'res_id': invoice.id,
            })
            invoice.with_context(no_new_invoice=True).message_post(
                attachment_ids=[att.id],
                body=_('Contractor invoice attached (not digitized).'))
            att.with_context(skip_ai_extract=True).register_as_main_attachment(force=True)

        return invoice

    def action_create_invoice(self):
        """Create the vendor bill and open it (single run, from the form)."""
        self.ensure_one()
        invoice = self._create_vendor_bill()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': invoice.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_batch_create_invoice(self):
        """Batch (list action): create a vendor bill for each eligible salary run."""
        created = skipped = 0
        errors = []
        for run in self:
            if run.invoice_id or run.state != 'approved_and_locked':
                skipped += 1
                continue
            if run._is_crypto_payment():  # crypto payees: no vendor bill
                skipped += 1
                continue
            try:
                run._create_vendor_bill()
                created += 1
            except Exception as e:  # noqa: BLE001
                errors.append('%s: %s' % (run.reference, str(e)[:120]))
        msg = _('%s vendor bill(s) created, %s skipped.') % (created, skipped)
        if errors:
            msg += ' ' + _('Errors: ') + ' | '.join(errors[:5])
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Create Vendor Bill'),
                'message': msg,
                'type': 'warning' if errors else 'success',
                'sticky': bool(errors),
            },
        }

    def action_batch_delete_invoice(self):
        """Batch (list action): delete each salary run's linked vendor bill. The
        account.move unlink override reverts the run to 'approved_and_locked' and
        clears invoice_id. Posted bills are unreconciled and drafted first."""
        removed = skipped = 0
        errors = []
        for run in self:
            bill = run.invoice_id
            if not bill:
                skipped += 1
                continue
            try:
                if bill.state == 'posted':
                    for ml in bill.line_ids:
                        (ml.matched_debit_ids + ml.matched_credit_ids).unlink()
                    bill.button_draft()
                bill.unlink()
                removed += 1
            except Exception as e:  # noqa: BLE001
                errors.append('%s: %s' % (run.reference, str(e)[:120]))
        msg = _('%s vendor bill(s) deleted, %s skipped.') % (removed, skipped)
        if errors:
            msg += ' ' + _('Errors: ') + ' | '.join(errors[:5])
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Delete Vendor Bill'),
                'message': msg,
                'type': 'warning' if errors else 'success',
                'sticky': bool(errors),
            },
        }

    def action_batch_post_invoice(self):
        """Batch (list action): confirm (post) each salary run's draft vendor bill."""
        posted = skipped = 0
        errors = []
        for run in self:
            bill = run.invoice_id
            if not bill or bill.state != 'draft':
                skipped += 1
                continue
            try:
                bill.action_post()
                posted += 1
            except Exception as e:  # noqa: BLE001
                errors.append('%s: %s' % (run.reference, str(e)[:120]))
        msg = _('%s vendor bill(s) confirmed, %s skipped.') % (posted, skipped)
        if errors:
            msg += ' ' + _('Errors: ') + ' | '.join(errors[:5])
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Confirm Vendor Bill'),
                'message': msg,
                'type': 'warning' if errors else 'success',
                'sticky': bool(errors),
            },
        }

    def action_batch_reset_invoice_draft(self):
        """Batch (list action): reset each salary run's posted vendor bill to draft
        (unreconciling first if needed)."""
        reset = skipped = 0
        errors = []
        for run in self:
            bill = run.invoice_id
            if not bill or bill.state != 'posted':
                skipped += 1
                continue
            try:
                for ml in bill.line_ids:
                    (ml.matched_debit_ids + ml.matched_credit_ids).unlink()
                bill.button_draft()
                reset += 1
            except Exception as e:  # noqa: BLE001
                errors.append('%s: %s' % (run.reference, str(e)[:120]))
        msg = _('%s vendor bill(s) reset to draft, %s skipped.') % (reset, skipped)
        if errors:
            msg += ' ' + _('Errors: ') + ' | '.join(errors[:5])
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Reset Vendor Bill to Draft'),
                'message': msg,
                'type': 'warning' if errors else 'success',
                'sticky': bool(errors),
            },
        }

    def action_batch_confirm_on_behalf(self):
        """Batch: confirm all selected salary runs on behalf of their employees."""
        if not self.env.user.has_group('hr_payroll_for_contractors.group_hpc_manager'):
            raise AccessError(_('Only payroll managers can confirm on behalf of employees.'))
        to_confirm = self.filtered(lambda r: r.employee_confirmation == 'waiting')
        to_confirm.sudo().write({'employee_confirmation': 'confirmed'})
        for run in to_confirm:
            run.message_post(
                body=_('Confirmed on behalf of %(employee)s by %(user)s.',
                       employee=run.employee_id.name,
                       user=self.env.user.name),
                subtype_xmlid='mail.mt_note',
            )
        skipped = len(self) - len(to_confirm)
        msg = _('%d salary run(s) confirmed.') % len(to_confirm)
        if skipped:
            msg += ' ' + _('%d skipped (already confirmed).') % skipped
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Confirm Instead of Employee'),
                'message': msg,
                'type': 'success',
                'sticky': False,
            },
        }

    def action_batch_unconfirm_on_behalf(self):
        """Batch: unconfirm all selected salary runs on behalf of their employees."""
        if not self.env.user.has_group('hr_payroll_for_contractors.group_hpc_manager'):
            raise AccessError(_('Only payroll managers can unconfirm on behalf of employees.'))
        to_unconfirm = self.filtered(lambda r: r.employee_confirmation == 'confirmed')
        to_unconfirm.sudo().write({'employee_confirmation': 'waiting'})
        for run in to_unconfirm:
            run.message_post(
                body=_('Unconfirmed on behalf of %(employee)s by %(user)s.',
                       employee=run.employee_id.name,
                       user=self.env.user.name),
                subtype_xmlid='mail.mt_note',
            )
        skipped = len(self) - len(to_unconfirm)
        msg = _('%d salary run(s) unconfirmed.') % len(to_unconfirm)
        if skipped:
            msg += ' ' + _('%d skipped (already waiting).') % skipped
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Unconfirm Instead of Employee'),
                'message': msg,
                'type': 'success',
                'sticky': False,
            },
        }

    def action_confirm_on_behalf(self):
        """Admin confirms the salary run on behalf of the employee."""
        self.ensure_one()
        if not self.env.user.has_group('hr_payroll_for_contractors.group_hpc_manager'):
            raise AccessError(_('Only payroll managers can confirm on behalf of an employee.'))
        self.sudo().write({'employee_confirmation': 'confirmed'})
        self.message_post(
            body=_('Confirmed on behalf of %(employee)s by %(user)s.',
                   employee=self.employee_id.name,
                   user=self.env.user.name),
            subtype_xmlid='mail.mt_note',
        )

    def action_unconfirm_on_behalf(self):
        """Admin retracts the employee confirmation on behalf of the employee."""
        self.ensure_one()
        if not self.env.user.has_group('hr_payroll_for_contractors.group_hpc_manager'):
            raise AccessError(_('Only payroll managers can unconfirm on behalf of an employee.'))
        self.sudo().write({'employee_confirmation': 'waiting'})
        self.message_post(
            body=_('Unconfirmed on behalf of %(employee)s by %(user)s.',
                   employee=self.employee_id.name,
                   user=self.env.user.name),
            subtype_xmlid='mail.mt_note',
        )

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
            employee_allowed_fields = {
                'adjustment_ids',
                'contractor_invoice_file',
                'contractor_invoice_filename',
            }
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

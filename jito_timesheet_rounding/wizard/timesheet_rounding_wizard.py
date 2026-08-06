# -*- coding: utf-8 -*-

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

from ..models.rounding import GRID_PRECISION_DIGITS, is_on_grid, round_to_grid
from odoo.tools import float_compare


class TimesheetRoundingWizard(models.TransientModel):
    """Manual, opt-in conversion of hand-picked timesheets to the tracking step.

    Nothing is written until the user confirms: the wizard shows every selected
    entry with its current and resulting value first.
    """

    _name = 'timesheet.rounding.wizard'
    _description = 'Convert Timesheets to Tracking Step'

    step_minutes = fields.Integer(
        string='Rounding Step (minutes)',
        default=lambda self: self.env.company._timesheet_rounding_minutes(),
        readonly=True,
    )
    rounding_method = fields.Selection(
        selection=[
            ('down', 'Round down'),
            ('up', 'Round up'),
            ('nearest', 'Round to nearest'),
        ],
        string='Rounding Method',
        default='nearest',
        required=True,
    )
    line_ids = fields.One2many(
        comodel_name='timesheet.rounding.wizard.line',
        inverse_name='wizard_id',
        string='Entries',
    )
    to_change_count = fields.Integer(compute='_compute_counts')
    unchanged_count = fields.Integer(compute='_compute_counts')
    blocked_count = fields.Integer(compute='_compute_counts')

    @api.depends('line_ids.will_change', 'line_ids.is_blocked')
    def _compute_counts(self):
        for wizard in self:
            lines = wizard.line_ids
            blocked = lines.filtered('is_blocked')
            changing = (lines - blocked).filtered('will_change')
            wizard.blocked_count = len(blocked)
            wizard.to_change_count = len(changing)
            wizard.unchanged_count = len(lines) - len(blocked) - len(changing)

    @api.model
    def _prepare_line_commands(self, timesheets):
        """One preview line per timesheet. Single source of truth for both callers."""
        return [Command.create({'timesheet_id': timesheet.id}) for timesheet in timesheets]

    @api.model
    def default_get(self, fields_list):
        """Fallback for callers that open the wizard through the context.

        The UI does not use this path: ``action_open_timesheet_rounding_wizard``
        creates the record with its lines and opens it by ``res_id``. Building
        the lines here means they only exist as unsaved commands in the browser,
        and the client drops ``timesheet_id`` on the way back because the field
        is not rendered — see the note on the view.
        """
        res = super().default_get(fields_list)

        if 'line_ids' not in fields_list:
            return res
        if self.env.context.get('active_model') != 'account.analytic.line':
            return res

        timesheets = self.env['account.analytic.line'] \
            .browse(self.env.context.get('active_ids', [])) \
            .filtered(lambda line: line.project_id)
        if not timesheets:
            raise UserError(_("Select at least one timesheet entry to convert."))

        res['line_ids'] = self._prepare_line_commands(timesheets)
        return res

    def action_apply(self):
        """Write the new durations. Only explicitly selected entries are touched."""
        self.ensure_one()

        lines = self.line_ids.filtered(lambda l: l.will_change and not l.is_blocked)
        if not lines:
            raise UserError(_(
                "Nothing to convert: every selected entry is already on the "
                "%(step)s minute grid or cannot be modified."
            ) % {'step': self.step_minutes})

        for line in lines:
            # Plain write: access rights, record rules and the validated-timesheet
            # guards all stay in force.
            line.timesheet_id.write({'unit_amount': line.new_value})

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Timesheets converted"),
                'message': _("%(count)s entr(ies) converted to the %(step)s minute grid.") % {
                    'count': len(lines),
                    'step': self.step_minutes,
                },
                'type': 'success',
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }


class TimesheetRoundingWizardLine(models.TransientModel):
    _name = 'timesheet.rounding.wizard.line'
    _description = 'Timesheet Rounding Preview Line'

    wizard_id = fields.Many2one(
        comodel_name='timesheet.rounding.wizard',
        required=True,
        ondelete='cascade',
    )
    timesheet_id = fields.Many2one(
        comodel_name='account.analytic.line',
        string='Timesheet',
        required=True,
        readonly=True,
    )

    date = fields.Date(related='timesheet_id.date', readonly=True)
    employee_id = fields.Many2one(related='timesheet_id.employee_id', readonly=True)
    project_id = fields.Many2one(related='timesheet_id.project_id', readonly=True)
    name = fields.Char(related='timesheet_id.name', string='Description', readonly=True)
    validated = fields.Boolean(related='timesheet_id.validated', readonly=True)
    invoice_id = fields.Many2one(
        related='timesheet_id.timesheet_invoice_id',
        string='Invoice',
        readonly=True,
    )

    current_value = fields.Float(
        string='Current',
        related='timesheet_id.unit_amount',
        readonly=True,
    )
    new_value = fields.Float(
        string='New',
        compute='_compute_new_value',
        digits=False,
    )
    will_change = fields.Boolean(compute='_compute_new_value')
    is_blocked = fields.Boolean(
        string='Cannot be converted',
        compute='_compute_blocked',
        help="Reported in the preview, never converted.",
    )
    blocked_reason = fields.Char(
        string='Skipped because',
        compute='_compute_blocked',
    )

    @api.depends('current_value', 'wizard_id.rounding_method', 'wizard_id.step_minutes')
    def _compute_new_value(self):
        for line in self:
            step = line.wizard_id.step_minutes
            method = line.wizard_id.rounding_method or 'nearest'
            new_value = round_to_grid(line.current_value, step, method)

            line.new_value = new_value
            line.will_change = not is_on_grid(line.current_value, step) and float_compare(
                new_value, line.current_value, precision_digits=GRID_PRECISION_DIGITS
            ) != 0

    @api.depends('validated', 'invoice_id', 'invoice_id.state')
    def _compute_blocked(self):
        """Entries the conversion must leave alone.

        Invoiced entries are checked first and are the important case. Applying
        the wizard writes ``unit_amount``, and ``tm_rate_card`` reacts by syncing
        ``tm_adjusted_hours`` through ``_syncing_adjusted_hours`` — the very flag
        its "locked once billed" guard skips. Converting a billed entry would
        rewrite invoiced hours with no warning, so it never reaches ``write()``.
        The same rule already governs the Re-sync action in tm_rate_card.
        """
        for line in self:
            invoice = line.invoice_id
            if invoice and invoice.state != 'cancel':
                line.is_blocked = True
                line.blocked_reason = _("Invoiced (%s)", invoice.name)
            elif line.validated:
                line.is_blocked = True
                line.blocked_reason = _("Validated")
            else:
                line.is_blocked = False
                line.blocked_reason = False

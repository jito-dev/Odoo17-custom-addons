# -*- coding: utf-8 -*-

from odoo import _, api, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare

from .rounding import GRID_PRECISION_DIGITS, is_on_grid

# Context key that lets automated flows bypass the grid check when they own the
# duration (leave allocation, data fixes). Never set from the UI.
SKIP_CHECK_CONTEXT_KEY = 'skip_timesheet_rounding_check'


class AccountAnalyticLine(models.Model):
    _inherit = 'account.analytic.line'

    # ------------------------------------------------------------------
    # GRID VALIDATION
    # ------------------------------------------------------------------

    def _timesheet_rounding_step(self):
        """Tracking step in minutes for this line's company, 0 when not applicable.

        Only timesheets are concerned. Plain analytic lines (the ones invoices and
        the accounting create) also live in this model and their ``unit_amount`` is
        a quantity, not a duration, so they must never be checked against an
        hours grid.
        """
        self.ensure_one()
        if not self.project_id:
            return 0
        company = self.company_id or self.env.company
        return company._timesheet_rounding_minutes()

    def _check_timesheet_rounding(self):
        """Raise if any line's Hours Spent is off the company tracking step."""
        if self.env.context.get(SKIP_CHECK_CONTEXT_KEY):
            return
        for line in self:
            step = line._timesheet_rounding_step()
            if not step or is_on_grid(line.unit_amount, step):
                continue
            raise ValidationError(_(
                "Tracked time must be a multiple of %(step)s minutes. "
                "Please adjust the duration manually.\n\n"
                "Entry: %(date)s — %(name)s\n"
                "Current value: %(value).4f h",
            ) % {
                'step': step,
                'date': line.date or '',
                'name': line.name or '/',
                'value': line.unit_amount,
            })

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines._check_timesheet_rounding()
        return lines

    def write(self, vals):
        """Validate only the lines whose tracked time actually changes.

        Deliberate: about a third of the existing entries predate the setting and
        are off-grid. Checking them on every write would make them uneditable —
        no one could fix a description or move them to another task. They stay as
        they are until someone genuinely changes the duration, and the manual
        wizard is the way to convert them in bulk.
        """
        if 'unit_amount' not in vals or self.env.context.get(SKIP_CHECK_CONTEXT_KEY):
            return super().write(vals)

        new_value = vals['unit_amount']
        changing = self.filtered(
            lambda l: float_compare(
                l.unit_amount, new_value, precision_digits=GRID_PRECISION_DIGITS
            ) != 0
        )
        res = super().write(vals)
        changing._check_timesheet_rounding()
        return res

    # ------------------------------------------------------------------
    # BULK CONVERSION
    # ------------------------------------------------------------------

    def action_open_timesheet_rounding_wizard(self):
        """Open the manual conversion wizard for the selected timesheets.

        The wizard record is created here, with its preview lines, and opened by
        ``res_id``. Leaving that to ``default_get`` would mean the lines exist
        only as unsaved commands in the browser, and the web client keeps values
        solely for fields declared in the view — ``timesheet_id`` is not, so it
        never made it back and confirming the wizard failed on a missing
        mandatory field. Creating server-side also keeps large selections out of
        the browser: the preview paginates instead of rendering every row.
        """
        timesheets = self.filtered(lambda l: l.project_id)
        if not timesheets:
            raise UserError(_("Select at least one timesheet entry to convert."))

        step = self.env.company._timesheet_rounding_minutes()
        if not step:
            raise UserError(_(
                "Company hours tracking rounding is disabled, so there is no step "
                "to convert to.\n\n"
                "Enable it under Settings → Timesheets → All Tracking Rounding first."
            ))

        wizard_model = self.env['timesheet.rounding.wizard']
        wizard = wizard_model.create({
            'line_ids': wizard_model._prepare_line_commands(timesheets),
        })

        return {
            'name': _("Convert selected entries to rounding step"),
            'type': 'ir.actions.act_window',
            'res_model': 'timesheet.rounding.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

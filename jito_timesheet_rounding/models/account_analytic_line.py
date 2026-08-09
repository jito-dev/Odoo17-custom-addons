# -*- coding: utf-8 -*-

from collections import defaultdict

from odoo import _, api, models
from odoo.tools import float_compare

from .rounding import GRID_PRECISION_DIGITS, format_duration, round_to_grid

# Context key that lets automated flows keep the duration they computed
# (imports, data fixes, migrations). Never set from the UI.
SKIP_ROUNDING_CONTEXT_KEY = 'skip_timesheet_rounding_check'

# Links added by ``project_timesheet_holidays`` to the timesheets it generates
# from time off. That module is not a dependency here — it may simply not be
# installed — so the fields are looked up rather than accessed directly.
LEAVE_LINK_FIELDS = ('holiday_id', 'global_leave_id')


class AccountAnalyticLine(models.Model):
    _inherit = 'account.analytic.line'

    # ------------------------------------------------------------------
    # SCOPE
    # ------------------------------------------------------------------

    def _is_leave_timesheet(self):
        """True for a timesheet ``project_timesheet_holidays`` generated from time off.

        That module writes ``unit_amount`` from the employee's working schedule
        and keeps it equal to the leave duration (``hr_holidays.py``,
        ``resource_calendar_leaves.py``). A 7.6 h day rounded to 7.5 h would
        leave the timesheet disagreeing with the leave it belongs to. The leave
        owns that number; we do not.

        It is not a dependency of this module, so its fields may not exist.
        """
        self.ensure_one()
        return any(
            self._fields.get(name) and self[name] for name in LEAVE_LINK_FIELDS
        )

    def _timesheet_rounding_step(self):
        """Tracking step in minutes for this line, 0 when it must not be rounded.

        Three exclusions, each for its own reason:

        - **No project.** ``account.analytic.line`` also stores the plain
          analytic lines invoicing and accounting create, whose ``unit_amount``
          is a quantity, not a duration. Snapping those onto an hours grid would
          corrupt accounting figures.
        - **Leave-generated timesheets** — see ``_is_leave_timesheet()``.
        - **Rounding disabled** on the company.
        """
        self.ensure_one()
        if not self.project_id or self._is_leave_timesheet():
            return 0
        company = self.company_id or self.env.company
        return company._timesheet_rounding_minutes()

    # ------------------------------------------------------------------
    # IMMEDIATE FEEDBACK
    # ------------------------------------------------------------------

    @api.onchange('unit_amount')
    def _onchange_unit_amount_round_to_step(self):
        """Correct the duration as soon as the user leaves the field.

        ``create()``/``write()`` already round on the way to the database, so
        this changes no stored value — it only moves the correction forward to
        where the person can still see it happen. Without it the field keeps
        showing the number that was typed until the record is reloaded, which
        reads as "the setting is not working".

        The message goes back as a **notification**, not a dialog: Odoo's web
        client renders an onchange warning as a toast unless ``type`` is
        ``'dialog'`` (``relational_model.js::_onchange``). Nothing went wrong
        here and nothing needs acknowledging, so a modal would be the wrong
        weight — this is an explanation, not an error.

        Grid-view cells do not go through onchange; they are handled by
        ``grid_update_cell`` on the server and rounded there like any other
        write.
        """
        step = self._timesheet_rounding_step()
        entered = self.unit_amount
        rounded = round_to_grid(entered, step)
        if float_compare(
            rounded, entered, precision_digits=GRID_PRECISION_DIGITS
        ) == 0:
            return

        self.unit_amount = rounded
        return {
            'warning': {
                'type': 'notification',
                'title': _("Rounded to %s minutes", step),
                'message': _(
                    "Time here is kept in %(step)s-minute steps, so your "
                    "%(entered)s is now %(rounded)s. Feel free to change it if "
                    "that is not what you worked.",
                    step=step,
                    entered=format_duration(entered),
                    rounded=format_duration(rounded),
                ),
            },
        }

    # ------------------------------------------------------------------
    # APPLYING THE GRID
    # ------------------------------------------------------------------

    def _round_timesheet_duration(self):
        """Snap Hours Spent onto the company step on the lines that need it.

        Used by ``create()`` only — see the note there on why ``write()`` does
        not go through this. Off-grid lines are corrected with a second write
        carrying the skip flag, so the correction cannot recurse.
        """
        for line in self:
            step = line._timesheet_rounding_step()
            rounded = round_to_grid(line.unit_amount, step)
            if float_compare(
                rounded, line.unit_amount, precision_digits=GRID_PRECISION_DIGITS
            ) != 0:
                line.with_context(**{SKIP_ROUNDING_CONTEXT_KEY: True}).unit_amount = rounded

    @api.model_create_multi
    def create(self, vals_list):
        """Round after the insert, not before it.

        ``write()`` below adjusts the values on their way to the database, which
        is cheaper. ``create()`` cannot: at this point ``project_id`` may still
        be absent from ``vals`` (it is computed from ``task_id``) and so may
        ``company_id`` (``hr_timesheet`` fills it from the employee). Both decide
        whether and how the line is rounded. Resolving them here would mean
        duplicating core's own resolution and re-duplicating it every time core
        changes it, so the line is created first and corrected after, when the
        real values are on the record.
        """
        lines = super().create(vals_list)
        if not self.env.context.get(SKIP_ROUNDING_CONTEXT_KEY):
            lines._round_timesheet_duration()
        return lines

    def write(self, vals):
        """Round the incoming duration before it reaches the database.

        Two filters, both deliberate:

        - **only when the duration actually moves.** Entries logged before
          rounding was switched on keep their stored value; nothing rewrites
          them in place. An edit that touches the description, the task or the
          project of a legacy 1:10 entry must leave those 1:10 alone. Only a
          duration the user is genuinely changing gets snapped onto the grid.
        - **per step, not per write.** ``vals`` carries one value for the whole
          recordset, but the step is a company setting and some of the lines may
          be out of scope entirely (leave-generated, non-timesheet). Lines are
          grouped by the step that applies to them and each group gets its own
          write. The common single-group case still issues a single UPDATE.
        """
        if 'unit_amount' not in vals or self.env.context.get(SKIP_ROUNDING_CONTEXT_KEY):
            return super().write(vals)

        new_value = vals['unit_amount']
        lines_per_step = defaultdict(lambda: self.browse())
        for line in self:
            unchanged = float_compare(
                line.unit_amount, new_value, precision_digits=GRID_PRECISION_DIGITS
            ) == 0
            step = 0 if unchanged else line._timesheet_rounding_step()
            lines_per_step[step] |= line

        if len(lines_per_step) <= 1:
            step = next(iter(lines_per_step), 0)
            return super().write(dict(vals, unit_amount=round_to_grid(new_value, step)))

        result = True
        for step, lines in lines_per_step.items():
            step_vals = dict(vals, unit_amount=round_to_grid(new_value, step))
            result = super(AccountAnalyticLine, lines).write(step_vals) and result
        return result

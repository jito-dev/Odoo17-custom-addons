# -*- coding: utf-8 -*-

from odoo import _, api, models
from odoo.exceptions import ValidationError
from odoo.tools import float_compare

from .rounding import GRID_PRECISION_DIGITS, is_on_grid

# Context key that lets automated flows bypass the grid check when they own the
# duration (leave allocation, data fixes, historical imports). Never set from the UI.
SKIP_CHECK_CONTEXT_KEY = 'skip_timesheet_rounding_check'


class AccountAnalyticLine(models.Model):
    _inherit = 'account.analytic.line'

    # ------------------------------------------------------------------
    # SCOPE
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

    def _is_new_for_rounding(self):
        """True when this entry was created once the rule was already in force.

        The business rule is that entries which predate the rule are out of its
        reach entirely: they keep their duration, stay editable to any value, and
        are never converted. Membership is decided by ``create_date`` against the
        boundary stamped on the company.

        Both timestamps come from ``cr.now()`` — the transaction clock Odoo fills
        ``create_date`` from — so the comparison is exact. ``>=`` puts an entry
        created in the very transaction that enabled the rule on the new side,
        which is the stricter and safer reading.

        A record still in memory has no ``create_date`` yet; ``create()`` below
        only calls this after ``super()``, so the value is always set by then.
        """
        self.ensure_one()
        company = self.company_id or self.env.company
        start = company._timesheet_rounding_start()
        if not start:
            return False
        return bool(self.create_date) and self.create_date >= start

    # ------------------------------------------------------------------
    # VALIDATION
    # ------------------------------------------------------------------

    def _check_timesheet_rounding(self):
        """Raise if any concerned line's Hours Spent is off the tracking step."""
        if self.env.context.get(SKIP_CHECK_CONTEXT_KEY):
            return
        for line in self:
            step = line._timesheet_rounding_step()
            if not step or not line._is_new_for_rounding():
                continue
            if is_on_grid(line.unit_amount, step):
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
        """Validate only entries the rule covers, and only when the duration moves.

        Two filters, both deliberate:

        - ``_is_new_for_rounding()`` keeps pre-existing entries out. They may be
          edited to any value, including another off-grid one. Checking them
          would freeze a third of the database — nobody could correct a duration
          that was wrong for an entirely different reason.
        - the value comparison keeps an unrelated edit (description, task,
          project) from raising on an entry that happens to be off-grid.
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

# -*- coding: utf-8 -*-
"""
Pure helpers for the tracking step. No ORM access, so they can be unit tested
directly and reused by the models and the export controller.

Durations are handled in hours (the unit ``account.analytic.line.unit_amount``
uses) and converted to minutes only for the grid arithmetic.

Note there is deliberately no ``round_to_grid`` here. Nothing in this module
ever computes a corrected duration: an off-grid value is reported to the user,
never replaced.
"""

from odoo.tools import float_compare

MINUTES_PER_HOUR = 60.0
HOURS_PER_DAY = 24.0

# Tolerance for grid comparisons. 5 decimal digits on a step count is ~0.01 s of
# drift: below any real duration, above float8 representation noise.
GRID_PRECISION_DIGITS = 5


def steps_in(hours, step_minutes):
    """Return how many steps of ``step_minutes`` fit in ``hours`` (may be fractional)."""
    if not step_minutes:
        return 0.0
    return (hours * MINUTES_PER_HOUR) / step_minutes


def is_on_grid(hours, step_minutes):
    """True when ``hours`` is an exact multiple of ``step_minutes``.

    A zero step means "no grid configured", in which case everything is valid.
    """
    if not step_minutes:
        return True
    steps = steps_in(hours, step_minutes)
    return float_compare(
        steps, round(steps), precision_digits=GRID_PRECISION_DIGITS
    ) == 0


def hours_to_excel_duration(hours):
    """Convert hours to the fraction of a day Excel uses for duration cells.

    Excel time values are day fractions: 1 h 10 min is 1.1666../24. Combined with
    the ``[h]:mm`` number format this renders as ``01:10`` and still sums as a
    real number, so ``=SUM()`` over the column stays correct.
    """
    return hours / HOURS_PER_DAY

# -*- coding: utf-8 -*-
"""
Pure helpers for the tracking step. No ORM access, so they can be unit tested
directly and reused by the models, the wizard and the export controller.

Durations are handled in hours (the unit ``account.analytic.line.unit_amount``
uses) and converted to minutes only for the grid arithmetic.
"""

import math

from odoo.tools import float_compare, float_round

MINUTES_PER_HOUR = 60.0
HOURS_PER_DAY = 24.0

# Tolerance for grid comparisons. 5 decimal digits on a step count is ~0.01 s of
# drift: below any real duration, above float8 representation noise.
GRID_PRECISION_DIGITS = 5

ROUNDING_METHODS = ('down', 'up', 'nearest')


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


def round_to_grid(hours, step_minutes, method='nearest'):
    """Snap ``hours`` to the ``step_minutes`` grid.

    ``method`` is one of 'down', 'up', 'nearest'. 'down' and 'up' move towards
    minus/plus infinity respectively, so they keep their meaning for the negative
    unit_amount values that correction entries use.
    """
    if not step_minutes:
        return hours
    if method not in ROUNDING_METHODS:
        raise ValueError("Unknown rounding method: %s" % method)

    steps = steps_in(hours, step_minutes)
    # Absorb float noise first, otherwise 0.75 h can arrive as 2.9999999 steps
    # and 'up' would push it to a whole extra step.
    steps = float_round(steps, precision_digits=GRID_PRECISION_DIGITS)

    if method == 'down':
        steps = math.floor(steps)
    elif method == 'up':
        steps = math.ceil(steps)
    else:
        # float_round uses HALF-UP (half away from zero), unlike Python's round()
        steps = float_round(steps, precision_digits=0)

    return (steps * step_minutes) / MINUTES_PER_HOUR


def hours_to_excel_duration(hours):
    """Convert hours to the fraction of a day Excel uses for duration cells.

    Excel time values are day fractions: 1 h 10 min is 1.1666../24. Combined with
    the ``[h]:mm`` number format this renders as ``01:10`` and still sums as a
    real number, so ``=SUM()`` over the column stays correct.
    """
    return hours / HOURS_PER_DAY

# -*- coding: utf-8 -*-
"""
Pure helpers for the tracking step. No ORM access, so they can be unit tested
directly and reused by the models.

Durations are handled in hours (the unit ``account.analytic.line.unit_amount``
uses) and converted to minutes only for the grid arithmetic.
"""

import math

from odoo.tools import float_compare

MINUTES_PER_HOUR = 60.0

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


def round_to_grid(hours, step_minutes):
    """Snap ``hours`` onto the nearest multiple of ``step_minutes``.

    The rule, in full:

    - **no step configured** -> the value is returned untouched;
    - **exactly zero** -> stays zero. An empty duration is a legitimate entry
      and must not become 15 minutes of work nobody did;
    - **already on the grid** -> returned unchanged, byte for byte. Rebuilding
      it from the step count would replace a stored ``1.25`` with a value that
      is equal but not identical, and every such write is a pointless UPDATE;
    - **anything else** -> nearest multiple, ties away from zero;
    - **never below one step in magnitude.** Rounding 5 minutes down to nothing
      loses work that was genuinely logged and leaves a 0:00 row that reads as a
      mistake. One step is the smallest the grid can express, so that is the
      floor.

    Ties are resolved with ``floor(steps + 0.5)`` rather than ``round()``:
    the builtin rounds half to *even*, so ``round(4.5) == 4`` but
    ``round(5.5) == 6``. On a 15-minute grid that sends 1:07:30 down to 1:00
    while 1:37:30 goes up to 1:45 — the same half-step landing on either side
    depending on where it falls. ``floor(x + 0.5)`` sends every tie up.

    Negative durations keep their sign; the magnitude rules are applied to
    ``abs(hours)`` so the grid behaves symmetrically around zero.
    """
    if not step_minutes:
        return hours
    if not hours:
        return 0.0
    if is_on_grid(hours, step_minutes):
        return hours

    steps = math.floor(steps_in(abs(hours), step_minutes) + 0.5)
    rounded = max(steps, 1) * step_minutes / MINUTES_PER_HOUR
    return math.copysign(rounded, hours)


def format_duration(hours):
    """Render decimal hours as ``h:mm``, for user-facing messages.

    ``1.3666…`` means nothing to the person who typed 1:22; telling them their
    "1.37 became 1.25" would be worse than saying nothing at all.
    """
    minutes = int(round(abs(hours) * MINUTES_PER_HOUR))
    return '%s%d:%02d' % ('-' if hours < 0 else '', minutes // 60, minutes % 60)

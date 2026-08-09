# -*- coding: utf-8 -*-


def migrate(cr, version):
    """Drop the boundary column 2.x used to decide which entries the rule covered.

    2.x *rejected* off-grid durations, so it needed a cut-off: entries logged
    before the rule was switched on had to stay out of its reach, or a third of
    the database would have become uneditable.

    3.0.0 rounds instead of rejecting. Nothing is ever blocked and nothing is
    rewritten in place — a duration is only snapped onto the grid when someone
    actually enters or edits it — so there is no longer anything for a cut-off
    to protect. ``res_company.timesheet_rounding_start_date`` is gone from the
    model; Odoo leaves the column behind, and an orphan column that used to
    drive the module's central rule is exactly the kind of thing that misleads
    whoever debugs this next.

    The data is not worth keeping: it recorded when rounding was first switched
    on, which no code reads any more.
    """
    cr.execute("""
        ALTER TABLE res_company
        DROP COLUMN IF EXISTS timesheet_rounding_start_date
    """)

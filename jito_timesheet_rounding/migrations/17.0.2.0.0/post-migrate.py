# -*- coding: utf-8 -*-


def migrate(cr, version):
    """Stamp the boundary for companies that already had rounding enabled.

    Up to 1.x the rule applied to every entry, so there was no boundary to
    record. 2.0.0 decides what the rule covers from
    ``res_company.timesheet_rounding_start_date``, and reads an empty date as
    "validate nothing" — the fail-safe direction, because the business rule is
    that pre-existing entries must never be blocked.

    Without this migration, a company that had the setting switched on before
    the upgrade would come out with the setting still on and no date, and the
    grid would silently stop being enforced.

    The upgrade moment is the correct boundary: everything logged up to here
    predates the new rule and must stay untouched, which is exactly what 2.0.0
    promises. ``now() at time zone 'UTC'`` is the transaction timestamp, the
    same clock ``create_date`` is filled from, so entries created afterwards
    compare cleanly against it.
    """
    cr.execute("""
        UPDATE res_company
           SET timesheet_rounding_start_date = now() at time zone 'UTC'
         WHERE timesheet_rounding_enabled IS TRUE
           AND timesheet_rounding_start_date IS NULL
    """)

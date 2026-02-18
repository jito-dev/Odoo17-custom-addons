# -*- coding: utf-8 -*-


def post_init_hook(env):
    """
    Initialize tm_adjusted_hours = unit_amount for all existing timesheets.

    This runs after the module is installed/upgraded to backfill the new
    tm_adjusted_hours column. Records created after this upgrade will have
    tm_adjusted_hours initialized via the create() override.
    """
    env.cr.execute("""
        UPDATE account_analytic_line
        SET tm_adjusted_hours = unit_amount
        WHERE tm_adjusted_hours IS NULL
    """)

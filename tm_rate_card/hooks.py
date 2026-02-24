# -*- coding: utf-8 -*-


def post_init_hook(env):
    """
    Initialize stored fields for all existing timesheets.

    This runs after the module is installed/upgraded to backfill new columns.
    Records created after this upgrade will have fields set via create() and write().
    """
    # Backfill tm_adjusted_hours = unit_amount for timesheets missing it
    env.cr.execute("""
        UPDATE account_analytic_line
        SET tm_adjusted_hours = unit_amount
        WHERE tm_adjusted_hours IS NULL
    """)

    # Backfill tm_billing_currency_id from the linked rate card entry
    env.cr.execute("""
        UPDATE account_analytic_line aal
        SET tm_billing_currency_id = rce.currency_id
        FROM tm_rate_card_entry rce
        WHERE aal.tm_rate_card_entry_id = rce.id
          AND aal.tm_billing_currency_id IS NULL
    """)

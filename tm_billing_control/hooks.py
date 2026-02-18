# -*- coding: utf-8 -*-

from odoo.tools.sql import SQL, column_exists


def pre_init_hook(env):
    """
    Migration hook: Drop old SQL view before upgrading to TransientModel.

    Version 1.3.x had tm_billing_dashboard as a SQL view.
    Version 1.4.x+ uses TransientModel (regular table).
    This hook drops the view so Odoo can create the table.
    """
    # Get cursor from environment
    cr = env.cr if hasattr(env, 'cr') else env

    # Drop views manually if they exist
    cr.execute("""
        SELECT table_name
        FROM information_schema.views
        WHERE table_schema = 'public'
        AND table_name IN ('tm_billing_dashboard', 'tm_billing_dashboard_line')
    """)

    views_to_drop = [row[0] for row in cr.fetchall()]

    for view_name in views_to_drop:
        cr.execute(SQL("DROP VIEW IF EXISTS %s CASCADE", SQL.identifier(view_name)))

    # Also check for materialized views
    cr.execute("""
        SELECT matviewname
        FROM pg_matviews
        WHERE schemaname = 'public'
        AND matviewname IN ('tm_billing_dashboard', 'tm_billing_dashboard_line')
    """)

    mat_views_to_drop = [row[0] for row in cr.fetchall()]

    for view_name in mat_views_to_drop:
        cr.execute(SQL("DROP MATERIALIZED VIEW IF EXISTS %s CASCADE", SQL.identifier(view_name)))

    # Add missing columns to account_analytic_line (v1.8.0+)
    # These are stored computed fields that may not have been created during upgrade
    if not column_exists(cr, 'account_analytic_line', 'is_invoiced'):
        cr.execute("""
            ALTER TABLE account_analytic_line
            ADD COLUMN is_invoiced BOOLEAN DEFAULT FALSE
        """)

    if not column_exists(cr, 'account_analytic_line', 'invoice_state'):
        cr.execute("""
            ALTER TABLE account_analytic_line
            ADD COLUMN invoice_state VARCHAR
        """)

    if not column_exists(cr, 'account_analytic_line', 'invoice_payment_state'):
        cr.execute("""
            ALTER TABLE account_analytic_line
            ADD COLUMN invoice_payment_state VARCHAR
        """)

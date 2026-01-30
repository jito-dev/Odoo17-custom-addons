# -*- coding: utf-8 -*-

from odoo import tools


def pre_init_hook(cr):
    """
    Migration hook: Drop old SQL view before upgrading to TransientModel.

    Version 1.3.x had tm_billing_dashboard as a SQL view.
    Version 1.4.x+ uses TransientModel (regular table).
    This hook drops the view so Odoo can create the table.
    """
    # Drop the old view if it exists
    tools.drop_view_if_exists(cr, 'tm_billing_dashboard')
    tools.drop_view_if_exists(cr, 'tm_billing_dashboard_line')

# -*- coding: utf-8 -*-
{
    'name': 'Billing Control & Batch Invoicing',
    'icon': 'tm_billing_control/static/description/icon.png',
    'version': '1.10.16',
    'category': 'Services/Project',
    'summary': 'Controlled batch invoicing for Time & Materials projects with preview and audit trail',
    'description': """
Billing Control & Batch Invoicing
==================================

This module provides controlled batch invoicing workflow for Time & Materials projects.

Key Features:
------------
* Billing Run/Batch management per (client, period)
* Preview billing before invoice creation with grouping controls
* Immutable audit trail (billing run → preview lines → invoice)
* Automatic selection of validated, billable, unbilled timesheets with locked rates
* Grouping by: customer, currency, service bucket (SO line), employee, rate, optional project/month
* State workflow: draft → preview → invoiced → closed
* Double-billing prevention via standard Odoo mechanisms
* Automatic rate card state transitions (invoiced_locked)
* Recompute preview while in draft state
* Links invoice lines to correct Sales Order lines for delivered/invoiced tracking

Scope:
------
This module handles billing batch workflow and invoice generation from validated timesheets.
Requires tm_rate_card module for rate resolution and timesheet validation.

    """,
    'author': 'JITO LTD',
    'website': 'https://jito.dev',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'account',
        'hr',
        'hr_timesheet',
        'timesheet_grid',
        'sale',
        'sale_timesheet',
        'tm_rate_card',  # Required for rate card integration
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/tm_billing_run_sequence.xml',
        'views/account_analytic_line_views.xml',
        'views/account_analytic_line_export_views.xml',
        'views/tm_billing_dashboard_views.xml',
        'views/tm_billing_run_views.xml',
        'views/tm_billing_run_line_views.xml',
        'views/tm_billing_control_menus.xml',
        'wizard/tm_billing_run_export_wizard_views.xml',
        'wizard/tm_billing_run_create_wizard_views.xml',
        'report/billing_run_timesheets_report.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'pre_init_hook': 'pre_init_hook',
}

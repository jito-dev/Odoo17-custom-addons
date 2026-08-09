# -*- coding: utf-8 -*-
{
    'name': 'Rate Card Management (Pricing Authority)',
    'icon': 'tm_rate_card/static/description/icon.png',
    'version': '1.18.0',
    'category': 'Services/Project',
    'summary': 'Time & Materials Rate Card - Single Source of Truth for T&M Pricing',
    'description': """
Rate Card Management
====================

This module provides deterministic Time & Materials pricing authority for Odoo.

Key Features:
------------
* Single source of truth for T&M pricing
* Multi-dimensional rate matching (company, client, project, service product, employee, currency)
* Sales Order integration - link rates to SO lines for contractual traceability
* Timesheet tracking - view validated timesheets and billable amounts per rate card
* Effective dating with overlap prevention
* Governance: draft → locked → invoiced_locked state progression
* Immutability rules to prevent retroactive changes
* Deterministic rate resolution with project-specific priority
* Multi-company support
* Historical auditability

Scope:
------
This module handles ONLY the Rate Card master data and resolution logic.
Timesheet validation, invoicing, and Sage export are handled by separate modules.

    """,
    'author': 'JITO LTD',
    'website': 'https://jito.dev',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'hr',
        'hr_timesheet',
        'timesheet_grid',  # Required for timesheet validation status tracking
        'product',
        'project',
        'mail',
        'sale',
        # timesheet_invoice_id, so_line and is_so_line_edited on account.analytic.line
        # come from here (sale_timesheet/models/account.py:41-47). They are read by the
        # invoiced lock and written by the SO-line assignment, so the dependency is real:
        # it only ever worked because sale_timesheet is auto_install.
        'sale_timesheet',
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/tm_rate_card_sequence.xml',
        'views/tm_rate_card_entry_views.xml',
        'views/tm_rate_card_timesheet_views.xml',
        'views/account_analytic_line_views.xml',
        'views/tm_rate_card_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'tm_rate_card/static/src/js/timesheet_totals_renderer.js',
            'tm_rate_card/static/src/xml/timesheet_totals_renderer.xml',
            'tm_rate_card/static/src/scss/timesheet_totals.scss',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
    'post_init_hook': 'post_init_hook',
}

# -*- coding: utf-8 -*-
{
    'name': 'Rate Card Management (Pricing Authority)',
    'version': '1.8.0',
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
    'author': 'Your Company',
    'website': 'https://www.yourcompany.com',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'hr',
        'hr_timesheet',
        'product',
        'project',
        'mail',
        'sale',
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
    'installable': True,
    'application': True,
    'auto_install': False,
}

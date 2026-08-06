# -*- coding: utf-8 -*-
{
    'name': 'Timesheet Tracking Rounding',
    'version': '17.0.1.0.1',
    'category': 'Services/Timesheets',
    'summary': 'Company tracking step for Hours Spent + [h]:mm XLSX export for Adjusted Hours',
    'description': """
Timesheet Tracking Rounding
===========================

Two independent features, both scoped to timesheets:

1. **Company hours tracking rounding.** A per-company setting requiring Hours Spent
   (``unit_amount``) to be a multiple of 15 or 30 minutes. Values are never rounded
   silently: a non-conforming entry is rejected with a message asking the user to
   adjust the duration. Existing entries are left untouched and stay editable.

2. **XLSX export of Adjusted Hours as a duration.** ``tm_adjusted_hours`` is exported
   with the Excel ``[h]:mm`` number format, so 1 h 10 min reads as ``01:10`` instead
   of the ambiguous ``1.17``. Hours Spent is deliberately left unchanged.

A manual bulk wizard converts hand-picked legacy entries to the configured step,
with a preview and a choice of round down / up / nearest.
    """,
    'author': 'JITO LTD',
    'website': 'https://jito.dev',
    'license': 'LGPL-3',
    'depends': [
        'hr_timesheet',
        'timesheet_grid',
        # timesheet_invoice_id, which the wizard uses to keep billed entries out
        # of the conversion. tm_rate_card reads the same field but never declared
        # the dependency, so it only ever worked where sale_timesheet happened to
        # be installed.
        'sale_timesheet',
        'tm_rate_card',
        'web',
    ],
    'data': [
        'security/ir.model.access.csv',
        'wizard/timesheet_rounding_wizard_views.xml',
        'views/res_config_settings_views.xml',
        'views/account_analytic_line_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}

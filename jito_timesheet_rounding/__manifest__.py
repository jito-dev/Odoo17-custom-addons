# -*- coding: utf-8 -*-
{
    'name': 'Timesheet Tracking Rounding',
    'version': '17.0.2.0.0',
    'category': 'Services/Timesheets',
    'summary': 'Company tracking step for Hours Spent + [h]:mm XLSX export for Adjusted Hours',
    'description': """
Timesheet Tracking Rounding
===========================

Two independent features, both scoped to timesheets:

1. **Company hours tracking rounding.** A per-company setting requiring Hours Spent
   (``unit_amount``) to be a multiple of 15 or 30 minutes. Values are never rounded
   silently: a non-conforming entry is rejected with a message asking the user to
   adjust the duration.

   The rule applies **only to entries created once the setting is switched on**.
   Everything that already existed keeps its value, stays fully editable and is
   never rewritten — not automatically, not in bulk, not on edit. The boundary is
   the timestamp put on the company the first time rounding is enabled.

2. **XLSX export of Adjusted Hours as a duration.** ``tm_adjusted_hours`` is exported
   with the Excel ``[h]:mm`` number format, so 1 h 10 min reads as ``01:10`` instead
   of the ambiguous ``1.17``. Hours Spent is deliberately left unchanged.
    """,
    'author': 'JITO LTD',
    'website': 'https://jito.dev',
    'license': 'LGPL-3',
    'depends': [
        'hr_timesheet',
        'timesheet_grid',
        'tm_rate_card',
        'web',
    ],
    'data': [
        'views/res_config_settings_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}

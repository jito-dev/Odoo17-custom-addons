# -*- coding: utf-8 -*-
{
    'name': 'Timesheet Tracking Rounding',
    'version': '17.0.3.3.0',
    'category': 'Services/Timesheets',
    'summary': 'Automatic 15/30-minute rounding of tracked Hours Spent',
    'description': """
Timesheet Tracking Rounding
===========================

A per-company setting that snaps Hours Spent (``unit_amount``) onto a 15- or
30-minute grid when a timesheet is saved. Nothing is rejected and nothing has to be
corrected by hand: durations go to the nearest step with halves upwards, and
anything above zero is worth at least one full step, so 5 minutes becomes 15 rather
than disappearing.

The correction happens as soon as the user leaves the field, with a short
notification explaining what changed and why, so nobody has to reload the page to
find out what was actually logged.

Rounding happens **on save, never as a sweep over stored rows**. Entries already in
the database keep their value; an edit that only changes the description or the task
leaves the duration alone. Timesheets generated from time off keep the exact duration
of the leave they belong to, and analytic lines without a project carry quantities
rather than durations and are left out entirely.
    """,
    'author': 'JITO LTD',
    'website': 'https://jito.dev',
    'license': 'LGPL-3',
    'depends': [
        'hr_timesheet',
        'timesheet_grid',
        'web',
    ],
    'data': [
        'views/res_config_settings_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'jito_timesheet_rounding/static/src/grid_cell_rounding.js',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}

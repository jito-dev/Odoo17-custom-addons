# -*- coding: utf-8 -*-
{
    'name': 'Public Holiday Timesheet Task',
    'version': '17.0.1.0.0',
    'category': 'Human Resources',
    'summary': 'Route public holiday timesheets to a dedicated "Public Holidays" task',
    'description': """
Public Holiday Timesheet Task
==============================
Separates public holiday timesheet generation from regular time-off timesheets.

Instead of logging all leave timesheets under the generic "Time Off" task,
public holidays are logged under a dedicated "Public Holidays" task with
descriptions like "<Holiday name> (1/1)" instead of "Time Off (1/1)".

Configurable via Settings > Timesheets.
    """,
    'author': 'JITO LTD',
    'depends': ['project_timesheet_holidays'],
    'data': [
        'views/res_config_settings_views.xml',
    ],
    'post_init_hook': 'post_init',
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
    'auto_install': False,
}

# -*- coding: utf-8 -*-
{
    'name': 'Time Off Type Timesheet Configuration',
    'version': '17.0.1.2.0',
    'category': 'Human Resources',
    'summary': 'Expose timesheet configuration on Time Off Types to HR managers',
    'description': """
Time Off Type Timesheet Configuration
======================================
Fixes the hidden timesheet section on Time Off Types so HR managers can
configure timesheet generation without developer mode.

Problems solved:
- The "Timesheets" section on Time Off Types is hidden behind developer mode
  (groups="base.group_no_one") in the Enterprise module.
- A circular compute dependency causes the "Generate Timesheets" checkbox to
  reset itself when checked (project compute re-triggers generate compute).

This module:
- Removes the developer-mode restriction so HR managers see the section.
- Overrides _compute_timesheet_generate to depend only on timesheet_task_id,
  breaking the circular dependency.
- Adds an onchange on timesheet_generate to auto-set/clear the internal project.
    """,
    'author': 'JITO LTD',
    'depends': ['project_timesheet_holidays'],
    'data': [
        'views/hr_leave_type_views.xml',
    ],
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
    'auto_install': False,
}

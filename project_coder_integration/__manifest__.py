# -*- coding: utf-8 -*-
{
    'name': 'Project Coder Integration',
    'version': '17.0.1.3.0',
    'category': 'Project',
    'summary': 'Integrate Coder.com workspaces with Odoo project tasks',
    'description': """
This module provides integration between Odoo project tasks and Coder.com workspaces.
Users can manage Coder workspaces directly from project tasks, including starting,
stopping, and monitoring workspace status.
    """,
    'author': 'JITO LTD',
    'website': '',
    'depends': [
        'project',
        'base',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/res_config_settings_views.xml',
        'views/project_task_views.xml',
    ],
    'external_dependencies': {
        'python': [
            'requests',
        ],
    },
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
    'auto_install': False,
}

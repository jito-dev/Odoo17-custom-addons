# -*- coding: utf-8 -*-
{
    'name': 'HR Recruitment — Stage default_get fix',
    'version': '17.0.1.0.0',
    'category': 'Human Resources/Recruitment',
    'summary': 'Stages created from a vacancy kanban become job-specific (not global)',
    'description': """
        Minimal forward-only fix for the stock Odoo 17 behaviour where stages
        created via the "+ Stage" button inside a vacancy's kanban end up
        global (visible in every other vacancy). After installing this module,
        such stages are pre-filled with job_ids = [current_vacancy].

        - No new models, no new fields, no migration.
        - Existing stages are not modified.
        - Stages created from Configuration → Recruitment → Stages stay global
          (unchanged behaviour).
        - Uninstall returns Odoo to stock behaviour with zero residual state.
    """,
    'author': 'Jito',
    'website': 'https://jito.dev',
    'depends': ['hr_recruitment'],
    'data': [],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}

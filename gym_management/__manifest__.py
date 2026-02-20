# -*- coding: utf-8 -*-
{
    'name': 'Gym Management',
    'version': '17.0.1.0.0',
    'category': 'Services/Gym',
    'depends': [
        'base',
        'mail',
        'maintenance',
    ],
    'data': [
        'security/rules.xml',
        "security/security.xml",
        'security/ir.model.access.csv',
        'views/gym_student_views.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}

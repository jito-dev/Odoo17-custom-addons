# -*- coding: utf-8 -*-
{
    'name': 'Jito Icons',
    'version': '17.0.1.1',
    'category': 'Hidden',
    'depends': ['base', 'web'],
    'data': ['data/ir_ui_menu_data.xml'],
    'post_init_hook': 'jito_icons.hooks:post_init_hook',
    'installable': True,
    'auto_install': False,
}

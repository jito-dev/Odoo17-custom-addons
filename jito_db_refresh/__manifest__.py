{
    'name': 'Jito DB Refresh',
    'version': '17.0.1.0.2',
    'category': 'Administration/Tools',
    'summary': 'Render the copy-paste command that refreshes a local Odoo '
               'DB + filestore from a remote production host.',
    'author': 'JITO LTD',
    'website': 'https://jito.dev',
    'license': 'LGPL-3',
    'depends': ['base'],
    'data': [
        'security/ir.model.access.csv',
        'wizards/db_refresh_command_wizard_views.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}

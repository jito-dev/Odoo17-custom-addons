{
    'name': 'Revolut Accounting Helper',
    'version': '17.0.1.2.0',
    'category': 'Accounting',
    'depends': ['base'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'views/res_config_settings_views.xml',
        'views/google_drive_upload.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}

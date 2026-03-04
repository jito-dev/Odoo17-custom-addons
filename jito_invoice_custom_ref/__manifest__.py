{
    'name': 'Custom Invoice Reference',
    'version': '17.0.1.2.0',
    'category': 'Accounting/Accounting',
    'summary': 'Add a lockable custom reference field to customer invoices',
    'author': 'JITO LTD',
    'website': 'https://jito.dev',
    'license': 'LGPL-3',
    'depends': ['account'],
    'data': [
        'views/account_move_views.xml',
        'views/report_invoice.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}

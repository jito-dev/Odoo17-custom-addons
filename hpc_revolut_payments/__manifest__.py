{
    'name': 'Payroll for Contractors – Revolut Payments',
    'version': '1.1.4',
    'category': 'Human Resources/Payroll',
    'summary': 'Stores Revolut Business payment details on contractor contracts and exports CSV batch payments',
    'author': 'JITO LTD',
    'website': 'https://jito.dev',
    'license': 'LGPL-3',
    'depends': ['hr_payroll_for_contractors'],
    'data': [
        'security/ir.model.access.csv',
        'views/hpc_contract_revolut_views.xml',
        'views/hpc_revolut_export_wizard_views.xml',
        'views/hpc_revolut_server_action.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}

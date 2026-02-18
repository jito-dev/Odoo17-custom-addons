# -*- coding: utf-8 -*-
{
    'name': 'VAT Checker',
    'version': '17.0.1.0.0',
    'category': 'Contacts',
    'summary': 'Validate EU VAT numbers via VIES REST API directly from the Contacts form',
    'description': '''
        Integrates with the EU VIES (VAT Information Exchange System) REST API to validate
        VAT numbers for company contacts. Adds a "Request VAT Info" button on the partner
        form and displays verified company data in a dedicated "VAT Info" tab.
    ''',
    'website': 'https://jito.dev',
    'depends': [
        'base',
        'contacts',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/res_partner_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}

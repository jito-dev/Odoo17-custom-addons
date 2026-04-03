{
    'name': 'Revolut Business API Integration',
    'version': '17.0.1.63.0',
    'category': 'Accounting',
    'summary': 'Revolut Business API OAuth2 setup helper',
    'description': """
        Provides a UI wizard for setting up the Revolut Business API OAuth2 flow.
        Covers certificate generation, JWT creation, API authorization, and token exchange.
    """,
    'depends': ['base', 'bus', 'account', 'jito_invoice_extract_ai'],
    'data': [
        'security/groups.xml',
        'security/ir.model.access.csv',
        'views/legacy_accounting_config_views.xml',
        'views/revolut_helper_views.xml',
        'views/revolut_gmail_message_views.xml',
        'views/revolut_account_map_views.xml',
        'views/fcf_csv_import_wizard_views.xml',
        'views/google_account_views.xml',
        'views/openai_config_views.xml',
        'views/menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'legacy_accounting_helper/static/src/css/legacy_accounting.css',
            'legacy_accounting_helper/static/src/js/revolut_auto_fetch.js',
        ],
    },
    'application': True,
    'installable': True,
    'license': 'LGPL-3',
}

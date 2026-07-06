{
    'name': 'Revolut Business API Integration',
    'version': '17.0.1.115.0',
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
        'views/revolut_injection_rule_views.xml',
        'views/fcf_csv_import_wizard_views.xml',
        'views/revolut_bill_match_wizard_views.xml',
        'views/revolut_rule_suggest_wizard_views.xml',
        'views/revolut_bill_link_wizard_views.xml',
        'views/revolut_invoice_link_wizard_views.xml',
        'views/account_move_reset_draft.xml',
        'views/revolut_bill_import_wizard_views.xml',
        'views/google_account_views.xml',
        'views/openai_config_views.xml',
        'views/menus.xml',
        'data/fcf_accounts_setup.xml',
        'data/injection_rules_seed.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'legacy_accounting_helper/static/src/css/legacy_accounting.css',
            'legacy_accounting_helper/static/src/js/revolut_auto_fetch.js',
            'legacy_accounting_helper/static/src/js/inline_boolean_toggle.js',
        ],
    },
    'application': True,
    'installable': True,
    'license': 'LGPL-3',
}

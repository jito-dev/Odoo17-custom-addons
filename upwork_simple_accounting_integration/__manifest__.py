{
    'name': 'Upwork Simple Accounting',
    'version': '1.5.5',
    'category': 'Accounting/Upwork',
    'summary': 'Upwork OAuth2 integration with transaction ledger and invoice generation',
    'description': """
Upwork Simple Accounting
========================
Provides:
- OAuth2 connection to Upwork API
- Organization selector and accounting entity auto-detection
- Transaction history download (Upwork accounting ledger)
- Full transaction detail viewer with raw JSON
- Invoice DOCX/PDF generation from transaction data
    """,
    'author': 'JITO LTD',
    'website': 'https://jito.dev',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'mail',
        'jito_document_template',
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/sequences.xml',
        'views/usa_settings_views.xml',
        'views/usa_transaction_views.xml',
        'views/usa_invoice_config_views.xml',
        'views/usa_openai_config_views.xml',
        'views/usa_contract_detail_views.xml',
        'views/usa_upwork_invoice_upload_views.xml',
        'views/usa_menus.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}

{
    'name': 'AI Invoice Data Extraction',
    'version': '17.0.1.2.0',
    'category': 'Accounting',
    'summary': 'Extract vendor bill data from PDFs using OpenAI',
    'description': """
        Automatically extract invoice data (vendor, dates, amounts, line items)
        from uploaded PDF files using OpenAI, replacing the Odoo IAP credit-based
        extraction with a self-hosted AI solution.
    """,
    'author': 'Jito',
    'website': 'https://jito.dev',
    'depends': [
        'account',
        'hr_recruitment_extract_openai',
    ],
    'data': [
        'views/account_move_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}

{
    'name': 'Company Card',
    'version': '17.0.1.9.0',
    'category': 'Website',
    'summary': 'Public shareable company business card page',
    'description': """
        Generate a publicly accessible, beautifully styled company card page
        to share with potential business partners.

        Features:
        - Token-based shareable URL (no login required)
        - Displays: company name, address, website, VAT, logo, director email
        - Publish/unpublish toggle in company settings
        - Regenerate token to revoke old links
    """,
    'author': 'Jito',
    'website': 'https://jito.dev',
    'depends': [
        'website',
        'hr_payroll_for_contractors',
    ],
    'data': [
        'views/res_company_views.xml',
        'views/company_card_templates.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'jito_company_card/static/src/scss/company_card.scss',
            'jito_company_card/static/src/js/company_card.js',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}

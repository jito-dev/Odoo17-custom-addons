{
    'name': 'IQ Tests',
    'version': '17.0.1.0.1',
    'category': 'Human Resources/Recruitment',
    'summary': 'Raven\'s Matrices integrated with Recruitment',
    'description': """
     IQ Test module with HR Recruitment integration.
    - Automated Test Generation per Job Position.
    - Applicant IQ Score tracking.
    - Secure access via Email or Unique Token.
    - Automated Email Invitations on Stage change.
    """,
    'author': 'alextranduil',
    'website': 'https://jito.dev',
    'depends': ['website', 'base', 'hr_recruitment', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'data/iq_data.xml',
        'data/mail_data.xml',
        'views/iq_backend_views.xml',
        'views/iq_frontend_templates.xml',
        'views/iq_menus.xml',
        'views/hr_job_views.xml',
        'views/hr_applicant_views.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'iq_tests_survey/static/src/css/style.css',
        ],
    },
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
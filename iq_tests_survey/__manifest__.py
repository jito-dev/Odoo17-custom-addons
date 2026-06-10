{
    'name': 'Cognitive Assessments',
    'version': '17.0.1.3.0',
    'category': 'Human Resources/Recruitment',
    'summary': 'Raven\'s Matrices integrated with Recruitment and Internal Employee Self-Serve Assessments',
    'description': """
     Cognitive Assessment module with HR Recruitment integration and Internal Employee access support.
    - Automated Assessment Generation per Job Position.
    - Applicant Cognitive Score tracking.
    - Secure access via Email or Unique Token.
    - Automated Email Invitations on Stage change.
    - Internal Employee self-serve assessments (access_mode=internal).
    - Role-based access: Cognitive Assessments Administrator and Cognitive Assessments User.
    """,
    'author': 'alextranduil',
    'website': 'https://jito.dev',
    'depends': ['website', 'base', 'hr_recruitment', 'mail'],
    'data': [
        'security/iq_security.xml',
        'security/iq_record_rules.xml',
        'data/iq_data.xml',
        'data/mail_data.xml',
        'views/iq_backend_views.xml',
        'views/iq_my_tests_views.xml',
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

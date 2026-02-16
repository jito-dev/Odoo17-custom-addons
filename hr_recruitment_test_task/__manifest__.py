{
    'name': 'Recruitment Test Task',
    'version': '17.0.1.0.0',
    'category': 'Human Resources/Recruitment',
    'summary': 'Manage technical test task submissions for candidates',
    'description': """
        This module allows recruiters to send technical test tasks to candidates.
        - Generates unique submission links
        - Allows multiple submissions (history)
        - Auto-moves candidates to "Submitted" stage
        - Email integration
    """,
    'author': "alextranduil",
    'website': "https://jito.dev",
    'category': 'Human Resources/Recruitment',
    'version': '17.0.1.0.0',
    'depends': ['hr_recruitment', 'website', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'data/mail_data.xml',
        'data/stage_data.xml',
        'views/hr_applicant_views.xml',
        'views/hr_job_views.xml',
        'views/website_templates.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
{
    'name': 'Recruitment Test Task',
    'version': '17.0.1.0.3',
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
    'depends': ['hr_recruitment', 'website', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'data/mail_data.xml',
        # 'data/stage_data.xml',  <-- REMOVED: Stages are now managed dynamically in hr_job.py
        'views/hr_applicant_views.xml',
        'views/hr_job_views.xml',
        'views/website_templates.xml',
    ],
    'pre_init_hook': 'pre_init_hook',
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
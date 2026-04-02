# -*- coding: utf-8 -*-
{
    'name': 'HR Recruitment Vacancy Page',
    'version': '17.0.1.18.0',
    'category': 'Human Resources/Recruitment',
    'summary': 'Dynamic public vacancy page with configurable job publishing',
    'description': '''
        Build dynamic vacancy pages from job configuration:
        - Configurable title, descriptions, salary range, experience
        - "Take from Job Context" toggles for each field
        - Adds salary and experience fields to Job Positions
        - Modern vacancy detail and listing page rendering
    ''',
    'website': 'https://jito.dev',
    'depends': [
        'hr_recruitment',
        'website_hr_recruitment',
        'hr_recruitment_extract_openai',
    ],
    'data': [
        'views/hr_job_views.xml',
        'views/website_vacancy_templates.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'hr_recruitment_vacancy_page/static/src/scss/vacancy_page.scss',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}

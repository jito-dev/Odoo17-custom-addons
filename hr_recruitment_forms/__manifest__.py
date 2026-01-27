# -*- coding: utf-8 -*-
{
    'name': 'HR Recruitment Forms',
    'version': '17.0.1.0.5',
    'category': 'Human Resources/Recruitment',
    'summary': 'Google Forms-like application forms for job recruitment',
    'description': '''
        Create form templates for job applications with:
        - Standalone form template management
        - Wizard-based question selection from templates
        - Consolidated question management on Job
        - Automatic applicant creation
        - Form responses viewing including sections
    ''',
    'author': 'alextranduil',
    'website': 'https://jito.dev',
    'depends': [
        'hr_recruitment',
        'website_hr_recruitment',
    ],
    'data': [
        # Security
        'security/hr_recruitment_forms_security.xml',
        'security/ir.model.access.csv',
        # Views
        'views/hr_form_template_views.xml',
        'views/hr_form_question_views.xml',
        'views/hr_form_response_views.xml',
        'views/hr_job_views.xml',
        'views/hr_applicant_views.xml',
        'views/menuitems.xml',
        # Wizards
        'wizards/hr_form_add_questions_wizard_views.xml',
        # Website
        'views/website_hr_recruitment_templates.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'hr_recruitment_forms/static/src/scss/forms.scss',
            'hr_recruitment_forms/static/src/js/form_submission.js',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
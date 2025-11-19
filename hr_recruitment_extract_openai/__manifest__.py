# -*- coding: utf-8 -*-
{
    'name': 'HR Recruitment OpenAI Extract & Match',
    'version': '17.0.2.0.0',
    'category': 'Human Resources/Recruitment',
    'summary': "Extract CV data, process bulk CVs, and AI-match applicants to jobs.",
    'description': """
This module consolidates OpenAI recruitment functionality:

1. **Single Applicant CV Extraction:**
   - Parses CVs for key data (name, email, phone, skills, degree).
   - Uses the Odoo job queue for background processing.

2. **Bulk CV Processing:**
   - Adds a 'Bulk CV Processing' tab to the Job Position.
   - Processes multiple CV attachments in the background to create applicants.

3. **Job Description (JD) Parsing:**
   - Upload a JD file to generate weighted 'Job Requirement Statements'.

4. **Applicant AI Matching:**
   - Compares applicant CVs against job requirements.
   - Provides a weighted match score and detailed explanation.
    """,
    'author': 'alextranduil',
    'website': 'https://jito.dev',
    'depends': [
        'hr_recruitment',
        'mail',
        'hr_recruitment_skills', # Required for skill processing
        'queue_job',             # For background processing
        'bus',                   # For user notifications
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/hr_job_requirement_tag_views.xml',
        'views/hr_applicant_views.xml',
        'views/res_config_settings_views.xml',
        'views/hr_job_views.xml',
    ],
    'assets': {},
    'external_dependencies': {
        'python': [
            'openai',
        ],
    },
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
    'auto_install': False,
}
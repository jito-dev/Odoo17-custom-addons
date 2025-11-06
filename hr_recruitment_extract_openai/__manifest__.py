# -*- coding: utf-8 -*-
{
    'name': 'HR Recruitment OpenAI Extract',
    'version': '17.0.1.0.0',
    'category': 'Human Resources/Recruitment',
    'summary': "Extract CV data for single applicants or in bulk from jobs using OpenAI.",
    'description': """
This module consolidates all OpenAI CV extraction functionality into one addon.

Features:

1.  **Single Applicant Extraction:**
    
    - Adds an 'Extract with OpenAI' button to the hr.applicant form.
    - Uses the Odoo job queue (queue_job) for background processing.
    - Notifies the user on start and completion.

    
2.  **Bulk CV Processing:**
    
    - Adds a 'Bulk CV Processing' tab to the hr.job form.
    - Allows uploading multiple CVs to a job.
    - A button processes all CVs in the background (queue_job) to create new applicants.
    - Notifies the user on start and completion.

This module depends on 'hr_recruitment_skills' to create and link skills
from the extracted data.
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
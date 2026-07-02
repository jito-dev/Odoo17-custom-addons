# -*- coding: utf-8 -*-
{
    'name': 'HR Recruitment Fireflies Interview Summary',
    'version': '17.0.1.0.0',
    'category': 'Human Resources/Recruitment',
    'summary': "Paste a Fireflies interview link on a candidate and get a client-ready AI summary.",
    'description': """
HR Recruitment Fireflies Interview Summary
==========================================

Lets a recruiter attach one or more Fireflies.ai interview links to a candidate
(hr.applicant) and generate a client-ready, AI-written summary of each interview.

For every interview the AI produces:
  - an executive summary (2-3 sentences, ready to forward to the client),
  - the candidate's strengths,
  - concerns / risks,
  - notable highlights / quotes,
  - an optional Question & Answer breakdown driven by a question template
    (reuses hr.form.template / hr.form.question from hr_recruitment_forms).

The result can be copied to the clipboard or exported to a clean PDF.

Design notes
------------
  - v1 is manual only: the recruiter pastes the Fireflies link, no webhook/cron.
  - Reuses the existing OpenAI plumbing (hr.applicant._openai_call) and the
    company-level Fireflies / OpenAI keys from hr_recruitment_extract_openai.
  - Transcript fetch + AI run happen in the background via queue_job.
    """,
    'author': 'alextranduil',
    'website': 'https://jito.dev',
    'depends': [
        'hr_recruitment',
        'hr_recruitment_extract_openai',  # OpenAI client (_openai_call) + Fireflies/OpenAI keys
        'hr_recruitment_forms',           # Question templates used as the Q&A lens
        'queue_job',                      # Background processing
        'mail',
        'bus',                            # User notifications
    ],
    'data': [
        'security/ir.model.access.csv',
        'report/interview_summary_report.xml',
        'report/interview_summary_templates.xml',
        'views/hr_applicant_interview_views.xml',
        'views/hr_applicant_views.xml',
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

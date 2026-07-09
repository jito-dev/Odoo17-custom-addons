# -*- coding: utf-8 -*-
{
    'name': 'HR Recruitment Fireflies Interview Summary',
    'version': '17.0.1.17.0',
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
  - notable highlights / quotes.

The summary is focused using the role context taken straight from the job's
Job Description (its extracted Job Requirements, or the description text as a
fallback) — no separate question template to maintain. Recruiters can also add
their own questions on an interview and have them answered from the saved
transcript, one answer per question.

The candidate's Fireflies Summary tab shows each interview's analysis inline as
a stacked card, so the summary is read without opening a dialog.

Each interview keeps a chatter log of its analysis, lets the recruiter add a
free-form note alongside the AI output, and links straight to the original
Fireflies recording.

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
        'hr_recruitment_forms',           # hr.form.template dependency (kept for compatibility)
        'hr_recruitment_job_stage_config',  # per-(job, stage) default interview questions (Phase 2)
        'queue_job',                      # Background processing
        'mail',
        'bus',                            # User notifications
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_cron_data.xml',
        'views/res_config_settings_views.xml',
        'views/hr_job_stage_config_views.xml',
        'views/hr_applicant_interview_views.xml',
        'views/hr_applicant_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'hr_recruitment_fireflies/static/src/scss/fireflies.scss',
        ],
    },
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

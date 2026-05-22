{
    'name': 'Recruitment Test Task',
    'version': '17.0.1.0.8',
    'category': 'Human Resources/Recruitment',
    'summary': 'Manage technical test task submissions for candidates',
    'description': """
        This module allows recruiters to send technical test tasks to candidates.
        - Generates unique submission links
        - Allows multiple submissions (history)
        - Auto-moves candidates to "Submitted" stage
        - Email integration

        v17.0.1.0.6:
        - Adds ``test_task_url`` Char on hr.job so the recruiter can attach a
          job-specific link (e.g. GitHub repo) that the invite email renders.
        - Adds a "Preview Invitation Email" button next to the URL field so
          the recruiter can verify the substitution via Odoo's built-in
          mail.template Preview.
        - Test Task stages are managed only on the recruitment kanban (via
          hr.recruitment.stage.job_ids); intentionally not surfaced on the
          job's Stages tab to keep the configuration screen uncluttered.
    """,
    'author': "alextranduil",
    'website': "https://jito.dev",
    'depends': [
        'hr_recruitment',
        'website',
        'mail',
    ],
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
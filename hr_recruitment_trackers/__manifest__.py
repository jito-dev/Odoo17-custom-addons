# -*- coding: utf-8 -*-
{
    'name': "HR Recruitment Trackers",
    'summary': "Advanced Link Tracking for Job Positions",
    'description': """
        Replaces standard Source tracking with advanced Link Trackers.
        Features:
        - Shortened URLs (e.g. /t/TOKEN)
        - UTM Campaign/Source/Medium integration
        - Click counting and statistics (IP, User Agent)
        - Expiration dates and usage limits
        - Custom payload support
    """,
    'author': "alextranduil",
    'website': "https://jito.dev",
    'category': 'Human Resources/Recruitment',
    'version': '17.0.1.0.0',
    'depends': ['hr_recruitment', 'utm', 'website'],
    'data': [
        'security/ir.model.access.csv',
        'views/hr_recruitment_tracker_views.xml',
        'views/hr_job_views.xml',
        'views/hr_applicant_views.xml',
    ],
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
}
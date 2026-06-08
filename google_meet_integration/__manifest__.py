{
    'name': 'Google Meet Integration',
    'version': '17.0.2.1.0',
    'category': 'Productivity/Calendar',
    'summary': 'Generate Google Meet URLs on demand via the Google Meet REST API v2.',
    'description': """
Google Meet Integration
=======================

Adds a "+ Google Meet" button to calendar events and a "Google Meet" option under
Appointment Type > Options > Videoconference Link. Meet URLs are minted on demand
through the Google Meet REST API v2 (https://meet.googleapis.com/v2/spaces).

Piggy-backs on the existing google_calendar module for per-user OAuth storage —
no separate connection flow, no full calendar sync required.

Incompatible with appointment_google_calendar (both claim the same selection key).
""",
    'depends': ['calendar', 'appointment', 'google_calendar'],
    'data': [
        'security/ir.model.access.csv',
        'views/calendar_event_views.xml',
        'views/appointment_type_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'installable': True,
    'license': 'LGPL-3',
}

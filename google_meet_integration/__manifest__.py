{
    'name': 'Google Meet Integration',
    'version': '17.0.3.0.0',
    'category': 'Productivity/Calendar',
    'summary': 'On-demand Google Meet URLs via the Google Meet REST API v2, '
               'Google Meet as the default videoconference for Appointments, '
               'and an on-demand "Sync now" with Google Calendar.',
    'description': """
Google Meet Integration
=======================

Mints Google Meet URLs on demand through the Google Meet REST API v2
(https://meet.googleapis.com/v2/spaces), reusing the existing google_calendar
per-user OAuth storage — no separate connection flow, no full calendar sync
required.

v17.0.2.2.0: the appointment-type "Google Meet (Call Stage)" videoconference
option (``google_meet_rest``) was removed — it required a Meet OAuth scope
connected accounts lack (403, no link), and Call Stage booking types are forced
to the native ``google_meet`` source by the call-stage Google Meet bridge. The
calendar-event Meet redirection support is unchanged.

v17.0.2.3.0: makes **Google Meet the default** videoconference source for every
Appointment Type (for an org that does not use Odoo Discuss video). New types
default to ``google_meet``, the "Videoconference Link" selector is hidden on the
Appointment Type form, and a ``post_init_hook`` flips existing ``discuss`` types
to ``google_meet`` (empty/no-video types are left untouched). This was
previously the standalone ``appointment_google_meet_default`` module, now merged
here. Adds a dependency on ``appointment_google_calendar`` (source of the native
``google_meet`` value).

v17.0.3.0.0: adds an on-demand **"Sync now"** with Google Calendar — a backend
server action + Calendar menu item (``action_sync_google_calendar_now`` on
``res.users``) and a matching button in the calendar's Google sync toolbar that
pulls the latest changes even when already connected (the stock button only
stops the sync).
""",
    'depends': [
        'calendar', 'appointment', 'google_calendar',
        # Source of the native 'google_meet' videocall source used as the
        # Appointment Type default below.
        'appointment_google_calendar',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/calendar_event_views.xml',
        'views/res_config_settings_views.xml',
        'views/appointment_type_views.xml',
        'views/calendar_sync_now.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'google_meet_integration/static/src/calendar_sync_now/calendar_sync_now.js',
            'google_meet_integration/static/src/calendar_sync_now/calendar_sync_now.xml',
        ],
    },
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'license': 'LGPL-3',
}

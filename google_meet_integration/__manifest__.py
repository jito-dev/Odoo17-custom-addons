{
    'name': 'Google Meet Integration',
    'version': '17.0.4.0.0',
    'category': 'Productivity/Calendar',
    'summary': 'Google Meet as the default videoconference for Appointments, '
               'a "Google Meet" calendar-event redirection label, and an '
               'on-demand "Sync now" with Google Calendar.',
    'description': """
Google Meet Integration
=======================

Relies on the NATIVE Google Calendar sync to attach Google Meet links (Odoo
sends ``conferenceData.createRequest`` on the standard calendar OAuth scope).
This module only: defaults every Appointment Type to the native ``google_meet``
videoconference source (and hides the selector), labels calendar events whose
location is a ``meet.google.com`` URL as "Google Meet" for the Join redirection,
warns when assigned staff have not connected Google Calendar, and adds an
on-demand "Sync now".

v17.0.4.0.0: **removed** the up-front Google Meet REST minting path
(``google.meet.service`` + ``meet.googleapis.com/v2/spaces``), the import-time
OAuth-scope monkeypatch of ``GoogleCalendarService._get_calendar_scope``, the
fallback-Meet-user setting, and the dead ``appointment.invite.meet_space_url`` —
all unused (Meet links come from native sync; the call-stage bridge uses the
native ``google_meet`` source). This eliminates the server-boot risk of patching
a private Odoo util. The ``calendar.event`` ``google_meet_rest`` redirection
label is kept (contract relied on by the call-stage bridge). Also adds a clean
"staff without Google Calendar" warning on the Appointment Type form (native
check, replaces the old ``users_wo_google_meet_msg``).

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

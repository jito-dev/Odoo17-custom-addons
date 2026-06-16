# -*- coding: utf-8 -*-
"""v17.0.2.2.0 — drop the 'google_meet_rest' appointment-type videocall source.

The "Google Meet (Call Stage)" option (key ``google_meet_rest``) on
``appointment.type.event_videocall_source`` is removed (it needed a Meet OAuth
scope connected accounts lack → 403, no link; Call Stage uses native
``google_meet`` instead). Flip any appointment type still parked on it to the
native ``google_meet`` BEFORE the selection value is cleaned up on load, so no
row is left holding an invalid key.

Note: the separate ``calendar.event.videocall_source`` 'google_meet_rest' key
is intentionally kept — different field, still drives the Join redirection.
"""


def migrate(cr, version):
    cr.execute(
        """
        UPDATE appointment_type
           SET event_videocall_source = 'google_meet'
         WHERE event_videocall_source = 'google_meet_rest'
        """
    )

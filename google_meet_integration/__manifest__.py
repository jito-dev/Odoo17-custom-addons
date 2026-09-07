{
    'name': 'Google Meet Integration',
    'version': '17.0.8.0.1',
    'category': 'Productivity/Calendar',
    'summary': 'Google Meet as the default videoconference for Appointments, '
               'a "Google Meet" calendar-event redirection label, and an '
               'on-demand "Sync now" with Google Calendar.',
    'description': """
Google Meet Integration
=======================

v17.0.8.0.0: **stop the per-occurrence invitation-email storm.**
  * During an INCREMENTAL sync stock sets ``send_updates=True``
    (``res.users._sync_google_calendar``: ``send_updates = not full_sync``), and
    ``_sync_odoo2google`` inserts every recurrence occurrence that has no
    ``google_id`` one-by-one. When a recurrence is restructured (gains an
    ``UNTIL`` rule, base time changes) its occurrences are re-created as brand-new
    events, so a long daily meeting fans out into HUNDREDS of ``_google_insert``
    calls — each telling Google ``sendUpdates=all`` → one attendee invitation
    email PER occurrence (~200 emails on prod 2026-07-15, uid=14).
  * A narrow ``_google_insert`` override forces ``send_updates=False`` ONLY for
    events that belong to a recurrence (``self.recurrence_id``); the base
    recurrence is synced separately and already notifies attendees once for the
    series. Genuine standalone new meetings keep ``send_updates`` intact so their
    legitimate invitations are still delivered. Patches untouched (the storm is
    from inserts). No stock changes, no monkeypatch.

v17.0.7.1.0: **stop the Google Calendar sync poison-pill infinite loop.**
  * The Google->Odoo sync (``GoogleSync._sync_google2odoo``) raises ``MissingError``
    when a recurrence base-time change cascades and deletes sibling occurrences
    still queued in the stock ``pending`` loop. The previous single retry was not
    enough: the cascade is deterministic, so the retry re-raised into the cron's
    ``cr.rollback()``, reverting the already-advanced ``calendar_sync_token`` and
    re-fetching the same poison forever (prod uid=14, recurrence #63742, 715
    occurrences pruned). The nightly cron had to be disabled by hand.
  * ``_sync_google2odoo`` now retries in a BOUNDED loop (``_MAX_G2O_RETRIES``) and,
    if it still cannot converge, SWALLOWS the final ``MissingError`` and returns an
    empty recordset so the sync token persists and the loop breaks. Recover any
    skipped batch via "Sync now" (forced full sync). ``MissingError`` only.

v17.0.7.0.2: **fix post-connect redirect landing on the website 404 page.**
  * ``action_google_calendar_connect`` returned the browser to ``/odoo`` after a
    successful Google consent — but ``/odoo`` is an Odoo 18 route and does not
    exist in Odoo 17, so the website module served its "page not found" editor
    page. Now returns to the Odoo 17 backend at ``/web``.

v17.0.7.0.0: **richer connection observability + friendlier Disconnect wizard.**
  * New stored bookkeeping on ``google.calendar.credentials``:
    ``calendar_last_sync_attempt`` (stamped on EVERY sync, whatever the outcome,
    so a stale/failing connection is obvious even when the error text is terse)
    and ``calendar_consecutive_failures`` (failure streak, reset on any success
    or reconnect). ``res.users`` exposes both as related fields (added to
    ``SELF_READABLE_FIELDS`` alongside the stock ``google_calendar_token_validity``
    so the owner sees when their token expires without a My-Profile AccessError).
  * ``res.users._sync_google_calendar`` now persists the FAILURE reason too, not
    only token errors: on any raise it rolls back the half-done sync (as the cron
    would), records the reason + bumps the streak in its own committed
    transaction, then re-raises — never swallowing. Mirrors the existing
    ``_refresh_google_calendar_token`` pattern.
  * My-Preferences "Google Calendar" tab gains: the ±1y **sync-window explainer**
    (pre-empts "some far-future meetings are missing"), **per-status guidance**
    (token expired / stopped / paused / not connected), a **failure-streak**
    warning, the last error shown under a "Google reported:" caption, and the
    connection-valid-until date.
  * The stock **Reset/Disconnect wizard** now explains, in plain language, what
    each option does — flagging in RED that "Delete from Google" erases the real
    Google events — via an inherited view (presentation only, no behaviour
    change).

v17.0.6.0.0: **self-service Google Calendar connection + sync resilience.**
  * A new **"Google Calendar" tab on My Preferences** (any internal user) shows
    a friendly connection STATUS badge, the LAST SUCCESSFUL SYNC time, and the
    LAST ERROR — including the OAuth consent ``?error`` and the token-refresh
    failure reason that stock Odoo silently swallows. Buttons: **Connect /
    Reconnect** (owner-only — OAuth binds the token to the consenting session),
    **Disconnect** (reuses the stock Reset-Account wizard, so the user can also
    delete their synced events from Odoo and/or Google), and **Sync now**.
  * Error capture: a thin override of the (multi-service) ``oauth2callback``
    controller — gated to ``service == 'calendar'`` and guarded against the
    public user — stores the OAuth error; ``_refresh_google_calendar_token`` is
    wrapped to persist its failure reason; ``_sync_google_calendar`` stamps the
    last success and clears the error. New stored fields live on
    ``google.calendar.credentials``; ``res.users`` exposes related + a computed
    status (all added to ``SELF_READABLE_FIELDS`` to avoid the My-Profile
    AccessError; raw tokens stay ``group_system``).
  * **Sync resilience** (``models/google_calendar_sync.py``): a narrow
    ``_inherit = 'google.calendar.sync'`` override wraps ``_sync_google2odoo``
    and, on ``MissingError`` only, retries over the surviving Google events.
    Fixes a stock "poison-pill" where a recurrence base-time change deletes a
    sibling event mid-loop → ``MissingError`` → cron rollback (incl. the
    sync_token) → the same poison record re-fetched every run → nothing imports
    for days. No verbatim copy of the stock method (upgrade-safe); the
    sync_token (written earlier in ``_sync_request``) now persists, breaking the
    loop. Recovery for anything skipped: the existing forced full "Sync now".

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

v17.0.5.0.0: the "Sync now" button now performs a **forced FULL sync over a
focused window** — recent past → near future, default ``-7d/+30d`` — instead of
the stock incremental ±1y pull. It clears the user's ``calendar_sync_token`` so
Google returns a full result set, then fetches it through a window-restricted
``GoogleCalendarService`` (asymmetric, unlike the stock symmetric
``google_calendar.sync.range_days``). This re-imports meetings that the
incremental sync silently never re-fetches (the common cause of "some meetings
are missing from my Odoo calendar"), while staying fast. The window is
overridable via the ``google_meet_integration.sync_now.past_days`` /
``...future_days`` system parameters. The calendar toolbar button was rerouted
through this same action so both surfaces behave identically. Cron and the
on-load calendar auto-sync are untouched (still stock incremental / ±1y).
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
        'views/res_users_google_calendar_views.xml',
        'views/reset_account_views.xml',
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

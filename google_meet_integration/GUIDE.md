# Google Meet Integration

## What this module does

Makes Google Meet the videoconference for an org that does not use Odoo Discuss
video, relying on the **native** Google Calendar sync to attach the Meet links
(Odoo sends `conferenceData.createRequest` on the standard calendar OAuth scope —
no extra scope, no separate REST call).

> **v17.0.4.0.0 — removed the up-front REST minting.** The on-demand Google Meet
> REST client (`google.meet.service` → `meet.googleapis.com/v2/spaces`), the
> import-time OAuth-scope monkeypatch of `GoogleCalendarService._get_calendar_scope`,
> the fallback-Meet-user setting, and the dead `appointment.invite.meet_space_url`
> were all deleted — they were unused (links come from native sync; the call-stage
> bridge uses the native `google_meet` source) and the monkeypatch was a
> server-boot risk. The `calendar.event` `google_meet_rest` redirection label is
> KEPT (contract relied on by `hr_recruitment_call_stage_google_meet`).

Integration points:

1. **Calendar event form** — the native "+ Odoo meeting" manual button is hidden
   (the link fills itself from native sync). Events whose `videocall_location` is
   a `meet.google.com` URL are labelled `google_meet_rest` so the Join button
   redirects to the raw Meet URL.

3. **Google Meet is the DEFAULT videoconference for Appointment Types
   (v17.0.2.3.0)** — for an org that does not use Odoo Discuss video:
   - new Appointment Types default `event_videocall_source = 'google_meet'`
     (`models/appointment_type.py`);
   - the "Videoconference Link" selector is **hidden** on the Appointment Type
     form (`views/appointment_type_views.xml`, inherits
     `appointment.appointment_type_view_form`; field set `invisible`, kept in
     DB / reachable in dev mode);
   - on install, `post_init_hook` (`hooks.py`) flips existing `discuss` types to
     `google_meet`; empty/no-video types are left untouched.
   This was previously the standalone `appointment_google_meet_default` module,
   merged here per "no new modules". Pulls in a dependency on
   `appointment_google_calendar` (source of the native `google_meet` value).

4. **On-demand "Sync now" with Google Calendar (v17.0.3.0.0)** — Odoo only
   pulls from Google when you open the Calendar (or via cron); there was no way
   to force a refresh while already connected (the stock toolbar button only
   STOPS the sync). Added:
   - **Backend engine + menu** — `res.users.action_sync_google_calendar_now`
     runs the per-user `_sync_google_calendar` on demand and returns a
     notification; surfaced as **Calendar → Sync Google now**
     (`views/calendar_sync_now.xml`, a server action). Acts on `env.user`
     (sync is per-user/per-token). Not-connected → friendly warning.
   - **Calendar button** — `static/src/calendar_sync_now/` patches
     `AttendeeCalendarController` with `onForceGoogleSyncNow` and appends a
     "Sync now" button to the `#google_calendar_sync` toolbar (shown when
     connected). It reuses the native `model.syncGoogleCalendar()` then reloads.
   Test: `tests/test_sync_now.py` pins the not-connected guard.

## Videocall URL is auto-filled (v17.0.2.1.0)

The Videocall URL field is designed to populate itself, so the manual
"create URL" buttons were removed from both calendar event forms
(`views/calendar_event_views.xml` now only hides
`set_discuss_videocall_location`; it no longer injects a Google Meet button):

- **Plain calendar events** created by a Google-synced user get a Meet link
  from the **native `google_calendar` two-way sync**: an event pushed to Google
  with empty `videocall_location` and empty `location` triggers
  `conferenceData.createRequest`, and Google's minted Meet URL syncs straight
  back into the field (`google_calendar/models/calendar.py`). This module does
  not implement that path — it is stock `google_calendar` behaviour.
- **Recruitment Call Stage bookings** also use the **native sync**:
  `hr_recruitment_call_stage_google_meet` forces every Call Stage booking type's
  `event_videocall_source` to `'google_meet'`, so Odoo attaches a Meet conference
  on sync and writes the URL onto `videocall_location`. The sync is asynchronous,
  so the link may arrive shortly after booking. See that module's GUIDANCE.

The field itself stays visible (read-only display of the auto link) along with
the native "Clear" and "Join" actions.

## Main models, views, business logic

| File | Purpose |
|---|---|
| `models/calendar_event.py` | Adds the `'google_meet_rest'` **redirection label** to the `videocall_source` selection, overrides `_compute_videocall_source` to detect `meet.google.com` URLs (native-sync links) and tag them, and overrides `_compute_videocall_redirection` so the Join redirection equals the raw `videocall_location`. NOTE: a *label/redirection* contract relied on by `hr_recruitment_call_stage_google_meet`'s tests — NOT a REST trigger (REST minting removed in v17.0.4.0.0). |
| `models/appointment_type.py` | Sets the **default** of `event_videocall_source` to `'google_meet'` (native source). Computes `google_meet_unsynced_staff_warning` (Html): when assigned staff have NOT connected Google Calendar, their bookings may sync without a Meet link — the warning lists them. Native-only: uses the public `res.users.is_google_calendar_synced()`, no REST/scope/fallback coupling. Clean successor of the removed `users_wo_google_meet_msg`. |
| `models/res_users.py` | `action_sync_google_calendar_now` — on-demand Google Calendar sync for the current user (backend twin of the "Sync now" button). Imports `GoogleCalendarService` lazily inside the method so a future rename of that private util can only break this one action at runtime, never abort boot. |
| `views/calendar_event_views.xml` | Hides the native "+ Odoo meeting" manual button on both the main and quick-create calendar event forms. |
| `views/appointment_type_views.xml` | Hides the "Videoconference Link" selector and, reusing the **same** `event_videocall_source` anchor (no extra view coupling), renders `google_meet_unsynced_staff_warning` after it (hidden when empty). |
| `views/calendar_sync_now.xml` | Server action + Calendar menu item "Sync Google now" (no-JS twin of the in-calendar button). |
| `views/res_config_settings_views.xml` | Adds the fallback user field inside the Google Calendar settings block. |

## Important patterns and constraints

- **No new persisted models.** `google.meet.service` is abstract. The module
  stores no secrets of its own — tokens live on `google.calendar.credentials`
  as provided by the enterprise `google_calendar` module.

- **OAuth scope composition.** The scope patch is idempotent (checks for the
  Meet scope before appending) and composes over any previous patch by
  capturing the original method at import time. Other modules that patch the
  same method will layer correctly as long as they follow the same pattern.

- **Incompatibility with `appointment_google_calendar`.** Both modules claim
  the same `'google_meet'` selection key but implement it differently:
  `appointment_google_calendar` synthesizes the URL via the Calendar sync
  pipeline (`conferenceData.createRequest` + `hangoutLink`), while this
  module mints the URL up-front via the Meet REST API. A `post_init_hook`
  refuses installation if `appointment_google_calendar` is present.

- **Single join link (no duplicate Meet URLs).** The enterprise
  `appointment` module computes `videocall_redirection` as
  `<base_url>/calendar/videocall/<token>` — an Odoo route that 302-redirects
  to `videocall_location` (`appointment/controllers/calendar.py:183`).
  Invitation/confirmation emails render the redirection URL on the "Join"
  button but the raw `videocall_location` in the body text, so a candidate
  used to see two *different* links for one meeting. `_compute_videocall_redirection`
  here points the redirection straight at `videocall_location` for Meet
  events, so button and text show an identical `meet.google.com` link.

- **Meet space reuse per invite.** `_prepare_calendar_event_values` reuses
  `appointment_invite.meet_space_url` when set and only mints (and then
  persists) a fresh space on first booking. Booking runs as a public/portal
  user, so the persist write is `sudo()`. This gives a candidate one stable
  join link across reschedules and protects the 60 QPM Meet API quota.

- **Fallback chain is lazy.** The fallback user is only queried when the
  preferred user has no token. If neither has a token, the calendar-event
  mint raises a user-facing error; the appointment-booking mint logs the
  exception and lets the booking complete without a videocall link (a
  broken link would be worse UX than no link on a public booking page).

- **Pre-existing Google Calendar connections** keep their old refresh token
  (calendar scope only) until the user re-consents. First Meet mint hits
  HTTP 403 "insufficient scope" and the module raises a `RedirectWarning`
  that opens `calendar.calendar_settings_action` (action label
  "Open Calendar Settings"). The user must disconnect and re-connect
  Google Calendar — thanks to the scope patch, the new consent URL requests
  both scopes. If the action ref is not found (module not loaded yet), the
  error falls back to a plain `UserError` with instructions.

- **Google Cloud project requirements.** The GCP project that backs Odoo's
  Google OAuth client must:
  1. Have the Google Meet API enabled.
  2. List `https://www.googleapis.com/auth/meetings.space.created` on the
     OAuth consent screen.
  Otherwise consent will fail with `invalid_scope`.

- **Google Workspace requirement.** The Meet REST API v2
  `spaces.create` endpoint may 403 for personal `@gmail.com` accounts. The
  admin-configured fallback user should be a Google Workspace account.

- **Meet API quota.** Default is 60 QPM per GCP project. Very busy public
  booking pages could throttle. Mitigated by per-invite reuse (see "Meet
  space reuse per invite") so each candidate mints at most one space; the
  manual "+ Google Meet" form button is the only remaining per-click mint.

## Known limitations

- No frontend interception of the "+ Google Meet" button (unlike the Odoo
  meeting button, which is purely frontend). A click on "+ Google Meet"
  saves the event first, then calls the server — a small UI freeze (under
  ~1 s typically) while the API call completes.
- The "+ Google Meet" form button mints a fresh space on every click (it is
  not tied to an `appointment.invite`, so there is nowhere to cache). The
  *booking* flow reuses the space per invite (see "Meet space reuse per
  invite" above); only the manual form button still re-mints.

## Integration test checklist

See the verification plan in
`/home/coder/.claude/plans/build-google-meet-integration-abundant-crystal.md`.

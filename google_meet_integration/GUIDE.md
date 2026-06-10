# Google Meet Integration

## What this module does

Lets Odoo users generate Google Meet URLs on demand for calendar events and
appointment bookings, without requiring the full two-way Google Calendar sync
that `appointment_google_calendar` needs.

Two integration points:

1. **Calendar event form** — historically a "+ Google Meet" button minted a
   Meet URL on demand. **As of v17.0.2.1.0 the manual create buttons are hidden**
   (see "Videocall URL is auto-filled" below): the link is meant to fill itself,
   so both the native "+ Odoo meeting" and the "+ Google Meet" buttons are gone
   from the event forms. The `action_set_google_meet_videocall_location` server
   method is kept for programmatic/back-compat use — it just has no button now.

2. **Appointment type Options → Videoconference Link** — adds a "Google Meet"
   choice. When a slot is booked, the Meet URL is minted atomically as the
   `calendar.event` is created (one write, no post-save patching).

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
- **Recruitment Call Stage bookings** do NOT use the native sync — they use
  this module's **up-front REST mint** instead (it is immediate and has a
  fallback user, which native sync lacks). `hr_recruitment_call_stage_google_meet`
  forces every Call Stage booking type's `event_videocall_source` to
  `'google_meet'`, so the mint below always runs and writes the link onto the
  event at booking time. See that module's GUIDANCE.

The field itself stays visible (read-only display of the auto link) along with
the native "Clear" and "Join" actions.

## Main models, views, business logic

| File | Purpose |
|---|---|
| `models/google_calendar_service_patch.py` | Wraps `GoogleCalendarService._get_calendar_scope` so the Google OAuth consent URL includes `https://www.googleapis.com/auth/meetings.space.created`. Only call site is `_google_authentication_url` (enterprise `google_calendar/utils/google_calendar.py:134`), so the patch is tightly scoped. |
| `models/google_meet_service.py` | `AbstractModel` wrapping `POST https://meet.googleapis.com/v2/spaces`. Handles the fallback chain (preferred user → admin-configured fallback user) and maps a 403 "insufficient scope" into a `RedirectWarning` that points the user at the Google Calendar settings page for re-consent. |
| `models/calendar_event.py` | Adds `'google_meet'` to the `videocall_source` selection, overrides `_compute_videocall_source` to detect `meet.google.com` URLs, exposes `action_set_google_meet_videocall_location` for the form button, and overrides `_compute_videocall_redirection` so the redirection URL equals the raw `videocall_location` for Meet events (see "Single join link" below). |
| `models/appointment_invite.py` | Adds `meet_space_url` (Char, `copy=False`) — the cached Meet URL for the invite. One invite maps to one `(recipient, appointment type)`, so reusing it keeps a stable join link across reschedules and avoids re-minting on every booking. |
| `models/appointment_type.py` | Adds `'google_meet'` to `event_videocall_source`. Overrides `_prepare_calendar_event_values` so the Meet URL is reused from `appointment_invite.meet_space_url` when present, else minted at booking time using the assigned staff user's token (with fallback) and persisted onto the invite. Renders a warning when staff users have no Google connection and no fallback is configured. |
| `models/res_config_settings.py` | Exposes the fallback Meet user (`ir.config_parameter` key `google_meet_integration.fallback_user_id`) as a setting under the Google Calendar block. |
| `views/calendar_event_views.xml` | Injects the "+ Google Meet" button into both the main and quick-create calendar event forms. |
| `views/appointment_type_views.xml` | Injects the connection-warning HTML widget under the videoconference source field. |
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

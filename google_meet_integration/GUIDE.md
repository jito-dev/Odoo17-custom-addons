# Google Meet Integration

## What this module does

Lets Odoo users generate Google Meet URLs on demand for calendar events and
appointment bookings, without requiring the full two-way Google Calendar sync
that `appointment_google_calendar` needs.

Two integration points:

1. **Calendar event form** — a "+ Google Meet" button next to the existing
   "+ Odoo meeting" button. Clicking it POSTs to the Google Meet REST API v2
   and populates `videocall_location` with the returned `meetingUri`.

2. **Appointment type Options → Videoconference Link** — adds a "Google Meet"
   choice. When a slot is booked, the Meet URL is minted atomically as the
   `calendar.event` is created (one write, no post-save patching).

## Main models, views, business logic

| File | Purpose |
|---|---|
| `models/google_calendar_service_patch.py` | Wraps `GoogleCalendarService._get_calendar_scope` so the Google OAuth consent URL includes `https://www.googleapis.com/auth/meetings.space.created`. Only call site is `_google_authentication_url` (enterprise `google_calendar/utils/google_calendar.py:134`), so the patch is tightly scoped. |
| `models/google_meet_service.py` | `AbstractModel` wrapping `POST https://meet.googleapis.com/v2/spaces`. Handles the fallback chain (preferred user → admin-configured fallback user) and maps a 403 "insufficient scope" into a `RedirectWarning` that points the user at the Google Calendar settings page for re-consent. |
| `models/calendar_event.py` | Adds `'google_meet'` to the `videocall_source` selection, overrides `_compute_videocall_source` to detect `meet.google.com` URLs, and exposes `action_set_google_meet_videocall_location` for the form button. |
| `models/appointment_type.py` | Adds `'google_meet'` to `event_videocall_source`. Overrides `_prepare_calendar_event_values` so the Meet URL is minted at booking time using the assigned staff user's token (with fallback). Renders a warning when staff users have no Google connection and no fallback is configured. |
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

- **Fallback chain is lazy.** The fallback user is only queried when the
  preferred user has no token. If neither has a token, the calendar-event
  mint raises a user-facing error; the appointment-booking mint logs the
  exception and lets the booking complete without a videocall link (a
  broken link would be worse UX than no link on a public booking page).

- **Pre-existing Google Calendar connections** keep their old refresh token
  (calendar scope only) until the user re-consents. First Meet mint hits
  HTTP 403 "insufficient scope" and the module raises a `RedirectWarning`
  pointing at Settings → Calendar with action label "Open Google Calendar
  Settings". Disconnect-and-reconnect will now request both scopes thanks
  to the scope patch.

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
  booking pages could throttle. Out of scope for v1 — caching per
  appointment type slot would need a separate field and TTL logic.

## Known limitations

- No frontend interception of the "+ Google Meet" button (unlike the Odoo
  meeting button, which is purely frontend). A click on "+ Google Meet"
  saves the event first, then calls the server — a small UI freeze (under
  ~1 s typically) while the API call completes.
- No Meet space reuse. Every click / booking mints a fresh space. Clicking
  twice quickly produces two different URLs, with only the last one saved.

## Integration test checklist

See the verification plan in
`/home/coder/.claude/plans/build-google-meet-integration-abundant-crystal.md`.

# Guidance — hr_recruitment_call_stage_google_meet

## What this module is for

A **thin bridge** that unifies two modules into one seamless,
Calendly-style recruiter flow:

- [`hr_recruitment_call_stage`](../hr_recruitment_call_stage/GUIDANCE.md) —
  the recruiter call-stage workflow (booking link, auto-advance, cockpit,
  `call_status`).
- [`google_meet_integration`](../google_meet_integration/GUIDE.md) — up-front
  Google Meet URL minting at booking time.

Design doc: [`../docs/call_stage_google_meet_seamless_plan.md`](../docs/call_stage_google_meet_seamless_plan.md).

**Neither parent is modified.** All coupling lives here. The bridge
`auto_install`s when both parents are present.

## What it adds (on `hr.applicant`)

| Field / method | Purpose |
|---|---|
| `meet_url` (computed, unstored) | Google Meet link of the **booked** calendar event for the applicant's current invite. Read straight off `calendar.event.videocall_location` — never re-minted. Empty until a slot is booked. |
| `call_booked_start` (Datetime, stored) | Start of the currently booked slot. Stamped on booking, updated on reschedule — recruiter sees the live time without opening the event. |
| `call_cancelled` (Boolean, stored) | Booked call was cancelled. Cleared automatically on a new booking. Drives `call_status = cancelled`. |
| `call_rescheduled` (Boolean, stored) | Booked call moved at least once. Drives `call_status = rescheduled`. |
| `call_status` (selection_add) | Extends the parent's 6 states with `rescheduled` and `cancelled`. |
| `action_join_call` | Opens `meet_url` in a new tab. |
| `_call_meet_on_booking / _on_reschedule / _on_cancel` | Lifecycle transitions called by the calendar.event hooks. |

## v17.0.1.3.0 — selection-key fix + custom-link cleanup

Two changes:

1. **Selection-key fix (regression).** `google_meet_integration` renamed
   its `appointment.type.event_videocall_source` option from `'google_meet'`
   to `'google_meet_rest'` (v17.0.2.1.0, label "Google Meet (Call Stage)"),
   but the bridge still wrote the old `'google_meet'` key. That raised
   `ValueError: Wrong value for appointment.type.event_videocall_source:
   'google_meet'` on every Call Stage config save — Call Stage bookings got
   **no Meet link at all**. All bridge references (`hr_job_stage_config.py`,
   `calendar_event.py`, `test_call_meet_bridge.py`, this doc) now use
   `'google_meet_rest'`.
2. **Custom-link cleanup.** Dropped `'manual_meeting_url'` from the
   `@api.depends` of `_compute_meet_url` / `_compute_call_status` — the
   parent module removed that override field (its GUIDANCE v17.0.15.0.0).

## Guaranteed Meet link on Call Stage bookings (v17.0.1.2.0)

The Google Meet link must land in `calendar.event.videocall_location` for every
booked call, with **zero recruiter configuration**. The bridge achieves this by
forcing the booking type into Google Meet mode and letting
`google_meet_integration` REST-mint the link up-front (the proven path):

- `hr.job.stage.config` (override `create` / `write`,
  `_apply_call_stage_google_meet_source`): when a config is `is_call_stage` with
  a `booking_appointment_type_id`, that appointment type's
  `event_videocall_source` is set to `'google_meet_rest'` (sudo). From then on
  `google_meet_integration._prepare_calendar_event_values` mints the Meet space
  via the Meet REST API as the event is created and writes the URL straight onto
  `videocall_location` — **instant, on the Odoo event, no Google sync needed**.
- The mint uses a **fallback chain** (assigned staff user → admin-configured
  fallback Meet user), so the link appears even when the specific recruiter has
  not personally connected Google. On config save the bridge logs a **warning**
  when neither a staff-user token nor a fallback user exists (booked calls would
  otherwise be link-less).

> Why REST, not native `google_calendar` sync: native sync only mints for the
> event organiser's *own* connected Google account (no fallback) and only after
> the next sync — unreliable for recruitment. REST mint is immediate and has a
> fallback, so the link is guaranteed on the event at booking time. (A prior
> v17.0.1.1.0 native-sync experiment was reverted for this reason.)

## Contracts you must respect

1. **`meet_url` is read-only and reuse-only.** It reflects the booked
   event's `videocall_location`, which is REST-minted up-front by
   `google_meet_integration` (and cached on `appointment.invite.meet_space_url`
   for reuse across reschedules). This bridge never mints — it only forces the
   booking type's source to `google_meet_rest` so the mint always runs. One booked
   event ⇒ one stable Meet link in the cockpit.

2. **`call_status` override restates ALL parent dependencies.** Overriding
   a computed field's method replaces its trigger set, so
   `_compute_call_status` here lists the parent's depends
   (`job_id, stage_id, call_outcome`) **plus**
   `call_cancelled, call_rescheduled`. If you add a new driver, add it to
   this decorator too. (Pre-v17.0.1.3.0 the parent also exposed
   `manual_meeting_url`; that custom-link override was removed from the
   parent module — see its GUIDANCE v17.0.15.0.0.)

3. **Recruiter outcomes win.** `attended` / `no_show` (set via
   `call_outcome`) are never masked by `cancelled` / `rescheduled`.

4. **Cancellation does NOT move the applicant off Call Booked.** We set
   `call_cancelled` + a recruiter To-Do (via the parent's
   `_call_stage_alert_recruiter`) and leave the stage alone. Candidate
   history stays visible in kanban; the recruiter decides re-invite /
   refuse / close. (Design-doc §8: chose the *state* over a separate
   "Call Cancelled" stage to avoid stage churn.)

5. **Reschedule is detected two ways** because the native flow may either
   move the event in place OR cancel+rebook:
   - `calendar.event.write` with a changed `start` on an active
     applicant event → `_call_meet_on_reschedule`.
   - `calendar.event.create` for an invite that already has a prior
     (archived) event → `_call_meet_on_booking` flags `call_rescheduled`
     and clears `call_cancelled`.

## Architecture invariants (do not break)

- The bridge `calendar.event.create` / `write` overrides run **after**
  `super()` (which chains through `hr_recruitment_call_stage`'s rename +
  auto-advance + reschedule note). They only *detect* transitions; all
  persisted state lives on `hr.applicant`.
- Lifecycle writes use `sudo()` — booking/cancel run as a public/portal
  user with no write access to `hr.applicant`.
- Hooks act only on events with both `applicant_id` and
  `appointment_invite_id`; unrelated calendar events fall straight through.

## Companion change in `google_meet_integration` (v17.0.2.0.0)

The single-join-link fix and Meet-space reuse live in the provider module,
not here:

- `_compute_videocall_redirection` → redirection equals `videocall_location`
  for Meet events, so invitation/confirmation emails show one identical
  `meet.google.com` link on both the "Join" button and the body text.
- `appointment.invite.meet_space_url` caches the minted Meet URL;
  `_prepare_calendar_event_values` reuses it across bookings/reschedules.

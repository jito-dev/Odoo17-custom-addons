# Jito Appointment Emails

## What this module does

Customises the three stock Odoo `appointment` mail templates so that:

1. **No meeting link is exposed by email.** The "How to Join" / videocall
   link block is removed from the booked, attendee-invitation and cancelled
   emails.
2. **Cancel & Reschedule are available from the email.** Explicit
   **Reschedule** and **Cancel** buttons are added, pointing at the public
   appointment portal routes.

## Main records & business logic

| File | Purpose |
|---|---|
| `data/mail_template_data.xml` | Re-declares `appointment.appointment_booked_mail_template`, `appointment.attendee_invitation_mail_template` and `appointment.appointment_canceled_mail_template` (only the `body_html` field). |

### Buttons → portal routes

| Button | Route | Notes |
|---|---|---|
| Reschedule | `/calendar/view/<access_token>?partner_id=<pid>` | Odoo's manage page (offers cancel + rebook). |
| Cancel | `/calendar/<access_token>/cancel?partner_id=<pid>` | Direct cancel; honours `appointment_type.min_cancellation_hours`. |

- **Booked** template (model `calendar.event`): `object.access_token`,
  `object.partner_id.id`. The old Join/View buttons are replaced.
- **Invitation** template (model `calendar.attendee`):
  `object.event_id.access_token`, `object.partner_id.id`. Accept/Decline are
  kept; a plain **View** button is the fallback for non-appointment invites.
- **Cancelled** template: only the videocall block is removed (no buttons —
  the event is already cancelled).

## Important patterns & constraints

- **mail.template body_html cannot be xpath-inherited.** The only supported
  customization is to re-declare the record by its full external id and ship
  a maintained copy of the body. This module therefore carries a **fork** of
  the three bodies. On each Odoo point-release, re-diff against
  `odoo17_enterprise/odoo/addons/appointment/data/mail_template_data.xml`.
- **Load order.** This module depends on `appointment`, so its data file
  loads after the stock templates and the re-declared records win
  (last-write by xml id). Records are NOT `noupdate`, so the override is
  re-asserted on every upgrade.
- **Button gating.** Buttons render only when both `appointment_type_id` and
  `access_token` are set, so plain (manually created) calendar events never
  emit broken portal links.
- **No collision with `google_meet_integration`.** That module only mints
  `videocall_location`; it does not touch these template records. Removing
  the email link is purely cosmetic and does not affect Meet minting.

## Testing

- Settings → Technical → Email Templates → open each template → Preview
  against a real `calendar.event` / `calendar.attendee`: confirm no
  "How to Join" text and that the buttons render with the correct hrefs.
- End-to-end: book an appointment, inspect the email, click Reschedule
  (lands on `/calendar/view/...`) and Cancel (respects
  `min_cancellation_hours`).

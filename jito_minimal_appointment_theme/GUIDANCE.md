# Minimalist Appointment Theme — Guidance

## What this module does
A **presentation-only** theme for the public Odoo Appointments booking flow.
It restyles the three booking steps into a clean, light, minimal look
(white surfaces, hairline borders, a single near-black "ink" accent) and adds
a breadcrumb step indicator. It changes **no booking logic**.

## Scope (important)
- **Recruitment bookings only.** Styling is gated so non-recruitment
  appointment pages are completely unaffected.
- **Styles + one small client-side flow tweak.** No controllers, no routes, no
  models, no fields. The Telegram/WhatsApp messenger capture, slot availability
  and form submission stay the stock behaviour from `appointment` +
  `hr_recruitment_call_stage`. The only JS is a thin override of the public
  slot-select widget (below) that adds a "Continue" step before navigating to
  the Details page — it changes *when* the navigation happens, not *where*.

## "Continue" step on time selection
Stock `appointment` navigates to the Details page the instant a time slot is
clicked. For recruitment bookings that feels abrupt, so
`static/src/js/minbook_slot_continue.js` `include()`s
`publicWidget.registry.appointmentSlotSelect` and overrides `_onClickHoursSlot`:

- It is a **no-op unless `#wrap` carries `o_jito_minbook`** (the recruitment
  gate). Otherwise `_super` runs and behaviour is byte-for-byte stock.
- Only the "direct navigate" branch (user-based bookings — Call Stage always is)
  is intercepted; the `time_resource` resource branch is left to core.
- Instead of redirecting, it selects the slot and injects a themed summary card
  (`.o_minbook_continue_wrap`: chosen day + time) with a **Continue** button.
- The Details URL is built **identically to core** (same hidden inputs + the
  slot's `data-url-parameters`); Continue just navigates there. Same destination,
  later moment.

## How the gating works
| Step | Template inherited | Gate (`recruitment_booking`) source |
|------|--------------------|--------------------------------------|
| 1 — Date & time | `appointment.appointment_info` | flag set by `hr_recruitment_call_stage` controller `_get_appointment_type_page_view` |
| 2 — Details | `appointment.appointment_form` | flag set by `hr_recruitment_call_stage` controller `appointment_type_id_form` |
| 3 — Booked | `appointment.appointment_validated` | derived read-only: the booking's `appointment_type` is referenced by some `hr.job.stage.config.booking_appointment_type_id` |

When the gate is true, the page `#wrap` gets the class **`o_jito_minbook`** and
a breadcrumb is rendered. Otherwise the page is byte-for-byte stock.

## Main parts
- `views/appointment_theme_templates.xml`
  - `minbook_breadcrumb` — reusable breadcrumb (`active_step` = date/details/booked).
  - Three `inherit_id` overrides that only (a) append `o_jito_minbook` to
    `#wrap` and (b) inject the breadcrumb. No behavioural markup is changed.
- `static/src/scss/minimal_theme.scss`
  - All rules are nested under `.o_jito_minbook` — the single scoping contract.
  - Design tokens are CSS variables (`--ink`, `--line`, `--surface-2`, radii,
    shadow) per the visual spec.
  - Includes the `.o_minbook_continue_wrap` summary-card styling for the
    "Continue" step.
- `static/src/js/minbook_slot_continue.js`
  - The only JS. Recruitment-gated override of the slot-select widget that turns
    the instant redirect on time-click into a "select + Continue" step (above).

## Constraints / gotchas
- **CSS scoping is the whole safety model.** Never write a top-level selector
  here — keep everything under `.o_jito_minbook` or it will leak site-wide.
- Odoo 17 ships **Bootstrap 5.1**, which does *not* expose the `--bs-btn-*`
  component variables (those are 5.2+). Buttons are themed by overriding the
  real `background-color` / `border-color` properties.
- The **calendar size/layout is intentionally left to core** — only colours
  (selected day = ink, today = gray, hover = surface-2, hairline borders) are
  restyled.
- The webfont (Plus Jakarta Sans) is loaded via `@import`; a system-font
  fallback keeps the page fully styled if that request is blocked.

## Install / upgrade
```bash
# install
odoo-bin -c <conf> -d <db> -i jito_minimal_appointment_theme --stop-after-init
# after edits
odoo-bin -c <conf> -d <db> -u jito_minimal_appointment_theme --stop-after-init
```
Depends on `hr_recruitment_call_stage` (pulls in `appointment`).

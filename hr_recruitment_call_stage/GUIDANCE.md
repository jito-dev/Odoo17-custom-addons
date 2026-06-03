# Guidance — hr_recruitment_call_stage

## What this module is for

Phased roadmap and consilium decisions: see
[`docs/call_stage_improvement_plan.md`](../docs/call_stage_improvement_plan.md).

Lets a recruiter mark a per-(job, stage) config row as a **Call Stage**.
When ticked:

- a required `Appointment Type` (`appointment.type`) appears next to the
  email template picker;
- the assigned `mail.template`'s `Book a call` button is auto-populated
  with a candidate-specific URL at email-render time (no recruiter has
  to paste anything);
- a companion **Call Booked** stage is auto-managed for the job (same
  pattern as `hr_recruitment_test_task._manage_test_task_stages`);
- when the candidate confirms a slot, the applicant is moved to
  `call_booked_stage_id`, with a chatter note recording the booking.

The created `calendar.event` is renamed to
`"{applicant.partner_name|name} — {appointment_type.name}"` so recruiters
scan a busy week-view at a glance. The event form gets an
**Open Applicant** smart button. The ICS attachment delivered to the
candidate is rewritten via `_get_customer_summary` to
`"Interview with {company} — {job}"` (the in-Odoo `event.name` stays
recruiter-friendly).

## v17.0.18.9.0 — Keep the call-invite mail.mail record

`_track_template` now forces `auto_delete=False` into the send options it
returns for the Call Stage tracked email (`hr_applicant.py`). Mail
templates default to `auto_delete=True`, which permanently deletes the
`mail.mail` right after a successful send — so the candidate's call
invite disappeared from **Settings > Technical > Emails** even though it
was delivered (the chatter `mail.message` log persisted, hence the
"email sent" entry). Forcing it off centrally keeps every Call Stage
send auditable regardless of which template (or recruiter-made copy) is
chosen, without touching each template's own flag. Covered by
`test_track_template_injection.test_track_keeps_mail_record`.

## v17.0.18.7.0 — Candidate profile link in the Meet description

`_call_stage_description_context()` now also returns `candidate_name`
(`partner_name|name|"Candidate"`, same fallback as the event title) and
`candidate_url` (`…/web#id=<id>&model=hr.applicant&view_type=form`). Both
renderers add a final **"Candidate (internal): &lt;linked name&gt;"**
section — a plain hyperlink in the same style as Reschedule/Cancel, for
recruiter/interviewer convenience.

- It is in the **shared** synced `calendar.event.description`, so the
  candidate sees it too — but the backend deep-link only resolves for
  internal users; the `(internal)` label makes the intent explicit. This
  deliberately re-introduces a recruiter link that an earlier version had
  removed (see the `_DESC_SENTINEL` comment), per product decision.
- HTML and plaintext (ICS) twins kept in lock-step — the module's core
  no-drift invariant. Idempotency sentinel unchanged.

## v17.0.15.0.0 — Custom booking-link feature removed

The recruiter-pasted / per-stage custom booking URL override is **gone**.
The Appointments-minted `appointment.invite.book_url` is now the single
source of every Call Stage booking link.

**Removed:**

- `hr.applicant.manual_meeting_url` (per-applicant pasted URL) — field,
  form widget, and its place in the `booking_url` priority chain.
- `hr.job.stage.config.default_meeting_url` (per-stage fixed room) —
  field and its priority-chain branch. (The field had already been
  commented out; this release deletes the remaining references.)
- The `has_override` / `override_url` short-circuits in
  `_compute_booking_url`, `_compute_call_status`,
  `action_send_invite_email`, and `_track_template`.

**Behaviour now:** `booking_url` resolves to
`appointment.invite.book_url` only; `call_status` is `no_link` until an
invite is minted. Recruiters can no longer substitute their own link —
all bookings flow through Appointments (and, with the Google Meet
bridge installed, get a Meet URL minted on the event). Auto-generation
of the invite and the Meet link is **unchanged**.

**Migration (`migrations/17.0.15.0.0/pre-migrate.py`):** drops the two
orphan columns (`hr_applicant.manual_meeting_url`,
`hr_job_stage_config.default_meeting_url`) with `DROP COLUMN IF EXISTS`
(idempotent). The companion bridge module
`hr_recruitment_call_stage_google_meet` (v17.0.1.3.0) drops
`manual_meeting_url` from its `@api.depends` declarations to match.

## v17.0.7.3.0 — Event description enrichment

`calendar.event.create()` now calls `_call_stage_enrich_description()`
post-`super()` for events that have both an `applicant_id` and an
`appointment_type_id`. It APPENDS (never rebuilds) to the stock booking
description (which keeps the Phone + Email form data) a `<div><ul>` block:

- **Odoo Candidate Link** — `…/web#id=<id>&model=hr.applicant&view_type=form`.
- **Reschedule / Cancel** — the public portal routes
  `/calendar/view/<access_token>?partner_id=<pid>` and
  `/calendar/<access_token>/cancel?partner_id=<pid>` (same routes the
  booking confirmation page uses; `partner_id` = `event.partner_id` or
  `appointment_booker_id`).
- **Job Posting** — only when `job.website_published and job.website_url`
  (field present only with `website_hr_recruitment`; soft-checked via
  `_fields` so we do NOT force that dependency).

Invariants:

- Runs in `create()` (not `_prepare_calendar_event_values`) so
  `access_token` and the native related `applicant_id` are populated.
  Composes cleanly with `google_meet_integration`'s
  `_prepare_calendar_event_values` override (independent concerns).
- **Idempotent** via the visible sentinel `"Odoo Candidate Link:"` — the
  `description` HTML sanitizer strips `data-`/`class` attributes, so the
  guard must be plain text, not an attribute.
- All user-derived strings (`applicant.display_name`, `job.name`) escaped
  via `markupsafe`. `write` uses `sudo()` (public booking user).
- Non-recruitment events (no applicant) are left untouched.

Note: email-side "no meeting link" + Cancel/Reschedule buttons live in the
separate **`jito_appointment_emails`** module (mail.template overrides).

## v17.0.18.2.0 — Rich candidate description reaches Google Calendar

**Problem.** The synced Google Calendar event only showed `Phone:` /
`Email:`. Google Calendar syncs the event body from
`calendar.event.description` (`google_calendar/models/calendar.py`
`_google_values` → `html_sanitize(self.description)`; `description` is in
`_get_synced_fields`). It NEVER reads the ICS DESCRIPTION. The rich
candidate content existed only in `_call_stage_get_customer_description()`
(the ICS path), so Google never saw it. The old `_call_stage_enrich_description`
only *appended* recruiter links to the bare Phone/Email body, and even that
was fragile: it ran AFTER `super().create()`, so Google's first
`_google_insert` captured the pre-enrich body and a slow/failed
`_google_patch` (timeout=3) could let a google→odoo pull revert the field.

**Fix — one source of truth, seeded at create.**

- `_call_stage_description_context(applicant, appt_type, start, stop,
  duration, base_url, token, partner)` computes the render-agnostic pieces
  (company, job, what-to-expect, recruiter, reschedule/cancel/job URLs).
  Takes primitives (not `self`) so it works pre-create from the create vals.
- Two renderers off that context — must stay in lock-step:
  - `_call_stage_render_description_html(ctx)` → sanitized HTML for
    `description` (Google + Odoo form).
  - `_call_stage_render_description_text(ctx)` → the existing plaintext ICS
    body (`_call_stage_get_customer_description` is now a thin wrapper).
- `create()` **pre-create** seeds `vals['description']` with the rich HTML
  and pre-generates `vals['access_token']`, so the FIRST push to Google
  already carries the rich content — no patch/round-trip race.
- `_call_stage_enrich_description()` is now a post-create **safety net**:
  for any applicant-linked event missing the body it REPLACES (no longer
  appends) it with the same HTML. Idempotent via the hidden comment sentinel
  `_DESC_SENTINEL` (`<!-- … -->`), which `html_sanitize` preserves and the
  candidate never sees.
- `write()` re-renders the description on reschedule (`start`/`stop` change)
  so the date/time on the candidate's calendar card stays accurate.

**Behaviour changes**

- The recruiter-only **backend applicant link** is removed from the synced
  description (it pointed at `/web#…hr.applicant`, useless/inaccessible to a
  candidate). Recruiters still reach the applicant via the **Open Applicant**
  smart button on the event form.
- The synced description is now the warm candidate copy (opener, when/where,
  what-to-expect, prep tip, recruiter, reschedule/cancel/job links, footer) —
  identical content to the ICS, rendered as HTML.

## v17.0.18.3.0 — Minimal description layout

The two renderers now produce a deliberately **minimal** layout (replacing
the warm/emoji design of v17.0.18.2.0), kept structurally identical between
HTML and plaintext:

1. **One-line confirmation** — `Your interview with <company> for the <role>
   role is confirmed.` (company/role bold in HTML). No date/time line: the
   Google Calendar card already shows those in its own fields.
2. **What to expect** — only when `hr.job.stage.config.what_to_expect` is
   filled; otherwise the whole section (header included) is omitted. Lines
   are joined plainly (no bullets, no emoji).
3. **Position** — the job name, linked to the public posting when the job is
   `website_published`, plain text otherwise. Shown only when a job exists.
4. **Need to make a change?** — `Reschedule · Cancel` (real portal anchors in
   HTML; labelled URL lines in text). Shown only with a usable access token +
   partner.

Sections separated by a short glyph constant `_DESC_DIVIDER` (`• • •`),
shared by both renderers. It is deliberately a short plain-text run rather
than a long box-drawing rule or an `<hr>`: a long rule can wrap and look
broken on a narrow mobile calendar card, and Google Calendar often strips
`<hr>`. The short glyph renders identically across Google web/mobile, the
ICS body, and email, and never wraps.

**Removed for good.** The warm opener (`You're all set! 🎉`), the when/where
block, the prep tip, the recruiter block, the footer, and ALL emoji are gone.
The now-unused helpers `_call_stage_footer_text`, `_call_stage_first_name`,
and `_call_stage_format_duration` were deleted with them. The hidden
`_DESC_SENTINEL` idempotency marker and the reschedule re-render are
unchanged. The old example's visible "Candidate reference" backend link is
NOT reintroduced — it pointed at `/web#…hr.applicant`, useless to a candidate.

## Contracts you must respect

1. **The booking URL comes from the stage's appointment type, never from
   the email template.** Templates only embed a `t-if`-guarded
   `<a t-att-href="ctx.get('booking_url')">` snippet — same snippet across
   every role-specific variant (Designer / Engineer / Sales).

2. **The "Book a call" button only renders during automatic stage
   tracking.** Manual "Send Email" actions from the applicant form do
   NOT flow through `_track_template` and therefore have no
   `booking_url` in context — the `t-if` guard hides the button. Do not
   reuse call-invite templates outside automatic stage transitions.
   _Note (v17.0.1.2.0):_ the user-facing fallback paragraph was removed
   from the shipped template. Manual sends produce a button-less email;
   Etap 3 of the improvement plan will introduce a stored `booking_url`
   field so manual sends render the button too.

3. **`hr.applicant.stage_id` is mutated only in `calendar.event.create`
   (post-booking advance), only when the applicant is still on the
   matching Call Stage AND the event's `appointment_type_id` matches
   `config.booking_appointment_type_id`.** Cancellation does NOT roll
   back — that is a deliberate decision; the recruiter manages it.

4. **One `appointment.invite` per `(applicant, appointment_type)`** —
   `_get_or_create_booking_invite` is the only creation path; it searches
   first via the native `appointment.invite.applicant_id` field shipped
   by `appointment_hr_recruitment` and creates only when no match. The
   uniqueness contract is *behavioural* (single-creation-path) rather
   than DB-enforced after Etap 2 — see v17.0.2.0.0 below.

5. **Recruiter-pool sync is opt-in REPLACE-with-union.**
   `hr.job.stage.config.recruiter_user_ids` pushes into
   `appointment.type.staff_user_ids` with two distinct modes per
   appointment.type:
   * If NO sibling Call Stage config declares any recruiters for this
     appointment type, sync is a no-op — the recruiter manages the
     pool directly on the appointment.type form.
   * If AT LEAST ONE sibling config declares recruiters, the
     appointment type is config-managed: staff_user_ids becomes the
     UNION across every such sibling. Removing a recruiter from a
     config evicts them from the pool unless another sibling still
     names them. Manual additions on the appointment.type form are
     overwritten once you opt in — that is intentional.
   See `_sync_recruiter_staff_users` for the authoritative docstring.

6. **Foundation dependency:** `_PAYLOAD_FIELDS` in the foundation must
   already list `is_call_stage`, `booking_appointment_type_id`, and
   `call_booked_stage_id` — see foundation GUIDANCE v17.0.1.0.13. The
   foundation bump is shipped in the same release bundle as this module.

## Architecture invariants (do not break)

- `_track_template` returns a recordset (with `with_context`-injected
  variables). It never returns a callable.
- `config.mail_template_id` is the source of truth for the per-job
  template. This module does NOT write to `stage.template_id`.
- The Call Booked global stage is data with `noupdate="1"` — recruiters
  may rename it; reinstalling must not trample manual edits.
- `_get_customer_summary` is overridden ONLY when the event has both
  `applicant_id` and `appointment_type_id` set. All other events fall
  through to `super()`.

## v17.0.1.1.0 — Auto-fill call-invite email template on `is_call_stage` flip

**What changed:** when a recruiter ticks `is_call_stage=True` on a
`hr.job.stage.config` row that has no `mail_template_id`, the shipped
template `mail_template_call_invite_generic` is auto-injected. Same on
`create()` and via the wizard onchange.

**Why:** before this, the recruiter had to (a) tick `is_call_stage`,
(b) pick an appointment type, AND (c) hop to the Email page to manually
pick the call-invite template. Three steps to enable one feature. The
auto-fill collapses (a)+(c) into a single tick while keeping the recruiter
in full control of the template.

**Preservation contract — do not break:**

1. **Explicit user pick wins.** If `vals` contains both
   `is_call_stage=True` AND `mail_template_id=<X>`, X is preserved. The
   `'mail_template_id' not in vals` guard in `write()` is what enforces
   this on multi-key writes.
2. **Pre-existing override wins.** If the row already has a
   `mail_template_id` before the tick, the auto-fill skips that row.
   `_auto_fill_call_invite_template` filters via
   `lambda c: not c.mail_template_id`.
3. **Untick is a no-op for the template.** When a recruiter unticks
   `is_call_stage`, `mail_template_id` is intentionally left untouched —
   it may be the template the recruiter actually wants as the per-job
   default. Clearing it would also re-enable the `stage.template_id`
   fallback unexpectedly.
4. **Idempotent re-tick.** `rows_enabling` is computed as
   `self.filtered(lambda c: not c.is_call_stage)` BEFORE super; a write
   that re-asserts an already-on tick produces an empty `rows_enabling`
   and the auto-fill never fires. Recruiter overrides survive across
   repeated saves.
5. **Multi-record write decides per row.** A bulk write toggling N rows
   on does not push the default into every row — `_auto_fill_call_invite_template`
   filters to rows with empty `mail_template_id` and writes the default
   only there.
6. **Shipped template missing → graceful no-op.** `env.ref(...,
   raise_if_not_found=False)` returns `False` during partial install or
   uninstall; the auto-fill skips without raising. Same pattern as
   `_sync_call_booked_membership`.

**Wizard support:** `hr.job.stage.create.wizard` (the "Add job-specific
stage" button on the job form) now exposes `is_call_stage`,
`booking_appointment_type_id`, `call_booked_stage_id` on a new "Call
Stage" notebook page. An `@api.onchange('is_call_stage')` auto-fills
`mail_template_id` in form state (recruiter sees the template change as
they toggle). `action_create` writes the call-stage payload onto the
freshly-created config row, which triggers the
`_auto_fill_call_invite_template` fallback even on programmatic callers
that skipped the onchange.

**What is NOT covered (deferred):**

The kanban "+ Stage" column-create flow still uses stock Odoo
`name_create` — a quick name-only input. It does not surface call-stage
fields at the creation moment. Recruiters who use that fast path
configure the call stage afterwards via the gear-icon popup on the new
column, where the auto-fill still works. Adding a richer column-create
UX would require an OWL patch on `KanbanRenderer` and is intentionally
left out per the foundation contract "no client-side patches when a
server-side hook suffices".

## v17.0.1.2.0 — Etap 1: foundations cleanup

Implements Etap 1 of `docs/call_stage_improvement_plan.md`. **No UI
additions, no model removals.** All changes are bug-fixes or
behavioural hardening that existing recruiter flows do not perceive
unless they were hitting one of the listed failure modes.

**Changes (all bug-fixes, additive on data):**

1. `hr.applicant.booking.invite.appointment_type_id` → `ondelete='restrict'`
   (was `cascade`). Deleting an `appointment.type` with live invites is
   now blocked with a database-level error — prevents the candidate's
   saved booking URL from 404-ing mid-flow.
2. `_call_stage_auto_advance_applicant` now silently no-ops when the
   applicant is archived (`active=False`) or refused
   (`refuse_reason_id` set). Closes the "stale link resurrects a refused
   candidate" hole.
3. `_call_stage_auto_advance_applicant` takes a `SELECT … FOR UPDATE`
   row lock on `hr_applicant` before reading `stage_id`. Removes the
   lost-update race between a concurrent recruiter stage-change and a
   candidate confirming a slot.
4. `_get_customer_summary` now reads
   `(applicant.company_id or env.company).name` instead of bare
   `env.company.name`. Multi-company recruiters no longer ship ICS with
   the wrong company brand.
5. Shipped `mail_template_call_invite_generic.body_html` no longer
   includes the "Booking link unavailable — please reply to this email"
   paragraph. Candidates never see internal failure copy.
6. `_track_template` now **suppresses the send** when a booking URL
   cannot be minted (missing appointment type, mint failure, empty
   `book_url`). It posts to chatter AND schedules a
   `mail.mail_activity_data_todo` on the responsible recruiter
   ("Fix Call Stage booking link"). Previously we sent the email with
   the fallback paragraph; now the email never reaches the candidate in
   a degenerate state.
7. Composite index `(job_id, stage_id, is_call_stage)` on
   `hr_job_stage_config` — added via `migrations/17.0.1.2.0/pre-migrate.py`,
   speeds the booking lookup at 10k-applicant scale.

**Template-body upgrade contract (do not break in future bumps):** the
pre-migrate compares the existing body_html to the v17.0.1.1.0 shipped
body (whitespace-normalised). On exact match it temporarily clears
`noupdate` so the new body XML loads; post-migrate re-asserts
`noupdate`. Recruiter-edited bodies are preserved untouched. Subsequent
template-body bumps must follow the same pristine-detection pattern.

**Recruiter alert helper:** `hr.applicant._call_stage_alert_recruiter(reason)`
posts to chatter AND schedules a To-Do activity on `applicant.user_id`
(falls back to `env.user`). Reuse this helper in future degraded-path
handlers; do NOT add silent failures.

## v17.0.2.0.0 — Etap 2: native model swap

Implements Etap 2 of `docs/call_stage_improvement_plan.md`. Replaces
our own join model `hr.applicant.booking.invite` with the native
`appointment.invite.applicant_id` field shipped by
`appointment_hr_recruitment` (auto-installed enterprise bridge).

**What was removed:**

- Model `hr.applicant.booking.invite` (file `models/hr_applicant_booking_invite.py`).
- Field `hr.applicant.booking_invite_ids`.
- Field `calendar.event.applicant_id` declared in our module — the
  native related stored field from `appointment_hr_recruitment` takes
  over (same field name, same semantics, but resolved as
  `appointment_invite_id.applicant_id`).
- Resolution loop inside `calendar_event.create()` that searched the
  join table. Now we read `appointment.invite.applicant_id` directly
  pre-super, and set it explicitly on `vals` as belt-and-braces for the
  auto-advance hook.
- Helper `_create_partner_for_booking` renamed to
  `_ensure_partner_for_booking` (same behaviour; aligned with native
  `action_makeMeeting` naming).
- Two `ir.model.access` rows for the dropped model.

**What was added:**

- File `models/appointment_type.py`: `@api.ondelete` blocks deletion of
  an `appointment.type` while any applicant-linked
  `appointment.invite` still references it. Replaces the
  `ondelete='restrict'` guarantee that lived on the dropped join
  model's `appointment_type_id` FK.

**Migration (`migrations/17.0.2.0.0/`):**

1. **pre-migrate.py** — copies `applicant_id` from each
   `hr_applicant_booking_invite` row onto the linked `appointment_invite`
   (only fills NULLs to preserve any native value). Renames the join
   table to `hr_applicant_booking_invite_etap2_backup` for rollback
   safety; the backup is NOT auto-dropped. Manually drop after the
   next release ships clean.
2. **post-migrate.py** — unlinks the `ir.model` record for the dropped
   model, cascading cleanup of `ir.model.fields`, `ir.model.access` and
   `ir.model.data`.

**Recovery if data is corrupted:**

```sql
ALTER TABLE hr_applicant_booking_invite_etap2_backup
    RENAME TO hr_applicant_booking_invite;
-- then revert to v17.0.1.2.0 code
```

**Contracts that changed:**

- Uniqueness `(applicant, appointment_type)` is no longer enforced by
  SQL. It is preserved behaviourally because
  `_get_or_create_booking_invite` is the *only* creation path. **Never
  call `appointment.invite.create({'applicant_id': ...})` from any
  other site in this module** — go through the helper.
- `book_url` was a related field on the dropped link model; callers
  who used `link.booking_url` must now use `invite.book_url` directly.

## v17.0.3.0.0 — Etap 3: recruiter cockpit

Implements Etap 3 of `docs/call_stage_improvement_plan.md`. **Adds UI**:
a Call Scheduling page on the applicant form with status, booking URL,
and action buttons. Replaces the implicit "advance on stage move →
template injection" flow with explicit recruiter actions that work from
any entry point (manual send included).

**New fields on `hr.applicant`:**

- `booking_url` (computed, unstored) — current applicant's
  `appointment.invite.book_url` for their job's Call Stage type. Empty
  when no invite exists.
- `call_outcome` (selection: pending / attended / no_show; default
  pending; `copy=False`) — recruiter-set after the call. Drives the
  terminal states of `call_status`.
- `call_status` (computed, stored, selection: no_link / link_ready /
  sent / booked / attended / no_show) — derived from invite presence,
  calendar event link, sent-marker chatter tag, and `call_outcome`.
  Stored so kanban / search use it.
- `call_scheduling_visible` (computed, unstored boolean) — view-only
  visibility flag; True when the applicant's job has any Call Stage
  config.

**New actions on `hr.applicant`:**

- `action_generate_booking_link` — mints the invite via
  `_get_or_create_booking_invite`. Idempotent.
- `action_send_invite_email` — mints if needed, renders the configured
  template with `booking_url` BOTH in context (legacy) and via
  `object.booking_url` (new path); queues `mail.mail`; posts a
  sent-marker to chatter (`<!-- call-invite-sent-marker -->`) which
  `_compute_call_status` reads.
- `action_resend_invite_email` — semantic alias.
- `action_mark_attended` / `action_mark_no_show` — write
  `call_outcome`. No-show also schedules a `mail.mail_activity_data_todo`
  on the responsible recruiter ("Follow up on no-show").

**Template change:**

Body now reads `ctx.get('booking_url') or object.booking_url` — BOTH
the legacy context path (from `_track_template`) AND the new field
path (works on manual sends) render the button. Migration uses the
same pristine-detection pattern as Etap 1; recruiter edits preserved.

**Contract that softened:**

GUIDANCE Contracts §2 — "The Book a call button only renders during
automatic stage tracking" — is no longer absolute. Manual sends and
"Send Email" wizard renders now produce a working button via the
field path. The note remains in §2 as historical context. Future
template bodies should prefer `object.booking_url` over
`ctx.get('booking_url')` to keep the manual-send path working.

**Sent-marker mechanic:**

`action_send_invite_email` posts a chatter message containing the
literal string `call-invite-sent-marker` (inside an HTML comment so
recruiters never see it). `_has_call_invite_sent_marker` greps chatter
for that string. Cheap, no extra fields, no schema cost. If you ever
need a richer audit log (open-tracking, click count), promote this to
a small dedicated model in Etap 7.

## v17.0.10.0.0 — Paired-stage name order + first-letter capitalisation

Two recruiter-facing naming tweaks:

- **Companion stage name order flipped.** `_sync_call_booked_membership`
  now names the paired stage `"<call stage name> — Call Booked"` (was
  `"Call Booked — <call stage name>"`), reading naturally as
  "*Interview* — Call Booked". Only the `_()` format string changed.
- **All new stage names start with a capital letter.** `hr.recruitment.stage`
  now overrides `create` (`@api.model_create_multi`) to upper-case the first
  character of `name` via the static helper `_capitalize_stage_name`
  (first char only — *not* `str.title()`/`capitalize()`, so the rest of the
  label and the " — Call Booked" suffix keep their casing; idempotent and
  empty-safe). Applies to **every** recruitment stage — kanban-created, job
  config wizard, and the auto-minted companion alike.

  Because the companion is created through this same path, its name is
  normalised automatically — no manual capitalisation at the call site.

  **Wizard knock-on:** `hr.job.stage.create.wizard.action_create` locates the
  just-created stage by name after `super()`; the persisted name may now
  differ from the raw wizard input, so the lookup matches
  `Stage._capitalize_stage_name(self.name)` instead of `self.name`.

  Scope note: this is a deliberate **global** behaviour on `hr.recruitment.stage`
  (all stages, not just call stages) — only the *first* letter is touched, so
  already-capitalised names (incl. all native Odoo defaults) are unchanged.
  No migration: existing stage names are left as-is; only new creates capitalise.

## v17.0.7.0.0 — Etap 8: per-Call-Stage paired Call Booked

Replaces the previous "one global Call Booked attached to many jobs"
design with a 1:1 paired stage per Call Stage. See
`docs/etap8_paired_call_booked.md` for the design doc.

**What changed:**

- `_sync_call_booked_membership` now creates (per config row) a fresh
  `hr.recruitment.stage` scoped to the job, named
  `"<call stage name> — Call Booked"` (order flipped in v17.0.10.0.0;
  see that section), and stamps its id into
  `call_booked_stage_id`. The legacy global `stage_call_booked` is no
  longer attached to any job by the new code path — it remains in
  `data/stage_data.xml` (with `noupdate=1`) only so historical
  references in old databases do not break.
- `@api.ondelete` on `hr.job.stage.config._archive_paired_call_booked_on_unlink`
  hides the paired stage's column from the job's kanban (sets
  `visible=False` on its `hr.job.stage.config` row) when the config row is
  removed. A second `@api.ondelete` on `hr.recruitment.stage` handles
  the kanban-gear "Delete Stage" path, where the FK CASCADE would
  otherwise skip the config-row ondelete entirely.
- Applicants currently on the paired stage are NOT moved or unlinked.
  The stage record itself stays — only the per-job kanban column is
  hidden. Recruiter can re-show the column via the job's Stages tab
  (toggle `visible=True`). Reason: `hr.recruitment.stage` has no
  `active` field in Odoo 17, so the foundation's per-job `visible`
  flag is the right archive primitive; it also keeps candidate history
  intact. Consilium decision: preserve candidate history.
- Recruiter pool field `recruiter_user_ids` keeps its semantics
  (opt-in UNION across sibling configs sharing one appointment type)
  but is relabelled to "Booking Calendars" / "Booking calendars
  (internal staff)" because users do not need to be in the recruitment
  group.

**Migration (`migrations/17.0.7.0.0/post-migrate.py`):**

- For every `hr.job.stage.config` row with `is_call_stage=True` whose
  `call_booked_stage_id` is empty OR still pointed at the legacy
  `stage_call_booked`, clear the pointer and re-invoke
  `_sync_call_booked_membership` so a fresh paired stage is minted.
  Applicants on the legacy global are left in place (user confirmed
  this environment is not prod).

**Contract updates:**

- Contracts §3 (auto-advance) is unchanged in API but now
  semantically writes the applicant onto a per-stage destination
  resolved through `config.call_booked_stage_id`. No call site needs
  to know about the rename.
- Paired stage names are NOT data-managed — once minted, recruiters
  may rename them freely. The reuse rule in
  `_sync_call_booked_membership` checks `call_booked_stage_id != legacy_global`
  to leave any non-legacy pointer untouched.

## v17.0.6.0.0 — Etap 7: recruiter calendar binding + unconditional body refresh

Two things at once because they were reported together.

**Recruiter pool sync (the new feature).**
`hr.job.stage.config` gains `recruiter_user_ids` (Many2many `res.users`).
When a Call Stage config has both `booking_appointment_type_id` AND
`recruiter_user_ids` filled, save propagates the recruiters into
`appointment.type.staff_user_ids` so the candidate-facing booking page
shows availability slots derived from those recruiters' internal Odoo
calendars (the native Appointments mechanism — see
`appointment/models/appointment_type.py:133` `staff_user_ids` and
`_compute_appointment_resource_ids`).

Sync semantics is **opt-in REPLACE-with-union** across every Call
Stage config that references the same appointment.type:

```
configs_with_recruiters := {cfg : cfg.is_call_stage = TRUE,
                                  cfg.booking_appointment_type_id = at,
                                  cfg.recruiter_user_ids ≠ ∅}

if configs_with_recruiters = ∅:
    appointment_type.staff_user_ids unchanged          # opt-out
else:
    appointment_type.staff_user_ids ←
        ⋃ {cfg.recruiter_user_ids for cfg in configs_with_recruiters}
```

Rationale: two Call Stages on different jobs may legitimately share
one appointment type with different recruiter pools; the union of all
declaring configs avoids stages stomping each other while still
removing a recruiter from the pool the moment no sibling config names
them. The opt-out path (no config declares recruiters) preserves the
"manage staff on the appointment.type form directly" workflow.

Sync triggers fire from both `create` and `write` on
`hr.job.stage.config`, gated on touching any of:
`recruiter_user_ids`, `booking_appointment_type_id`, `is_call_stage`.
The helper itself reads the freshly-saved values back from the DB so
the union is computed on the new state.

Views surface `recruiter_user_ids` (as `many2many_tags`) on three
editing surfaces:

- `view_hr_job_stage_config_form_call` (config popup)
- `view_hr_recruitment_stage_form_call_inherit` (kanban gear → Edit
  Stage → Call Stage Configuration inline tree)
- `view_hr_job_stage_create_wizard_form_call` (Add job-specific stage
  wizard)

The wizard mirrors the field and forwards it into the freshly-created
config row in `action_create`.

The empty/one/several-recruiter consequence is conveyed through native
Odoo affordances rather than a coloured `alert` block: a `placeholder`
on the empty field ("Empty → candidate first picks the meeting-type
owner (often Administrator)") plus a `help=` tooltip enumerating the
three outcomes. Kept English to match the rest of the module's labels.
(History: a UA `alert alert-info` banner was replaced in v17.0.18.6.0.)

Foundation contract update: `hr_recruitment_job_stage_config`
v17.0.1.0.15 reserves `recruiter_user_ids` in `_PAYLOAD_FIELDS` so
the scope-flip cleanup in `hr_recruitment_stage._inverse_scope` sees
rows carrying only this payload as "override" rows (not auto-rows
safe to delete on scope flip back to `global`).

**Unconditional body refresh (the bug fix).**
v17.0.5.0.0's pre-migrate relied on (a) the `Booking link unavailable`
substring marker to locate stale bodies, and (b) flipping
`ir_model_data.noupdate=false` so the manifest XML body would reload
during upgrade. We observed at least one install where running
`-u hr_recruitment_call_stage` left the canonical body unchanged — the
noupdate trick did not produce a reload. Root cause is still
unidentified (suspected: upgrade ordering vs. our migration phase).

`migrations/17.0.6.0.0/pre-migrate.py` stops trusting either lever:

- It runs a direct
  `UPDATE mail_template SET body_html = <SHIPPED_BODY>` on the
  canonical row (resolved via `ir_model_data`), every upgrade,
  unconditionally.
- It then scans every `mail.template` referenced by an
  `is_call_stage=TRUE` config row. If the body is *broken* — defined
  as carrying the legacy marker OR using `ctx.get('booking_url')`
  without the `or object.booking_url` companion — it gets the same
  forced rewrite. Well-formed recruiter customisations (those that
  already render a guarded `object.booking_url` button) are
  preserved.

The "broken" detector errs on the side of repairing — if you write a
recruiter-customised body without the `object.booking_url` reference,
that body WILL be overwritten on next upgrade. Document the customised
body in a recruiter-owned template (separate `xml_id`, no `ctx.get`)
to opt out.

## v17.0.5.0.0 — Etap 6: stale body sweeper

Implements Etap 6 of `docs/etap6_body_refresh.md`. Pure migration; no
new fields, models, or views.

**Problem:** a recruiter pasted a URL into `manual_meeting_url` and
sent the invite via the cockpit's **Send Invite Email** button; the
candidate received an email containing the legacy *"Booking link
unavailable — please reply to this email and we will schedule
manually."* paragraph. That paragraph only ships in the v17.0.1.1.0
body. Earlier pre-migrates only refresh the body when the DB row
byte-matches a known shipped variant after whitespace normalisation;
any WYSIWYG re-save, JSONB-dict storage edge, or recruiter duplicate
defeats the match and leaves the legacy body in place.

**What this release does:**

- `migrations/17.0.5.0.0/pre-migrate.py` — scans every `mail.template`
  row whose `body_html` contains the literal substring
  `Booking link unavailable`:
  - On the canonical row (matched via `ir_model_data`): clears
    `noupdate=False` so the v17.0.5.0.0 XML body in
    `data/mail_template_data.xml` reloads.
  - On duplicates / detached rows: directly rewrites `body_html` to
    the current shipped body. We do not touch the row's
    `ir_model_data` (if any) — we never claim ownership of recruiter
    duplicates.
  - Logs the rewritten row ids for audit. Recruiter customisations
    layered on top of the legacy paragraph need manual re-application.
- `migrations/17.0.5.0.0/post-migrate.py` — re-asserts
  `noupdate=True` on the canonical row so subsequent upgrades respect
  recruiter edits (same contract as `data/mail_template_data.xml`).

**Contracts preserved:**

- Bodies without the `Booking link unavailable` marker are **never**
  touched. Recruiters who genuinely customised the body keep it.
- Idempotent: re-running the migration on a refreshed DB finds zero
  matching rows and exits without writes.
- Body uses `ctx.get('booking_url') or object.booking_url` (kept as in
  v17.0.3.0.0 / 17.0.4.2.0). Drop only the `ctx.get` half if a future
  rewrite removes `action_preview_call_invite` and external recruiter
  tooling that passes `booking_url` via context.

**Regression tests** (`tests/test_etap6_body_refresh.py`):

1. A `mail.template` containing the legacy body is rewritten by the
   pre-migrate function; the resulting body uses `object.booking_url`
   and no longer contains the legacy fallback paragraph.
2. A `mail.template` whose body does NOT contain the legacy marker is
   left byte-identical after the migration (recruiter customisation
   preserved).
3. An applicant sent via `action_send_invite_email` produces a queued
   `mail.mail` whose body contains the auto-minted Appointments
   `book_url` — confirms the live render path off a fresh body.
   (Pre-v17.0.15.0.0 this test pasted a `manual_meeting_url`; that
   override field was removed — see the v17.0.15.0.0 section.)

## v17.0.4.2.0 — Etap 5: kanban gear access + manual meeting URL

Implements Etap 5 of the improvement plan
(`docs/etap5_kanban_gear_and_manual_url.md`).

**Two problems solved:**

1. *Booking link missing on manual sends.* Installations that migrated
   through 17.0.1.2.0 / 17.0.3.0.0 ended up with the body flagged as
   "customised" (because pre-migrate only matched against a single
   shipped variant, and JSONB-dict bodies were originally compared raw),
   so the v17.0.3.0.0 XML body that reads `object.booking_url` never
   loaded. Pre-migrate now matches against the *union* of every
   historical shipped body and force-clears `noupdate` on a match.
2. *Call-stage settings unreachable from the kanban gear.* The native
   gear opens `hr.recruitment.stage`. We inherit its form and append a
   "Call Stage Configuration" notebook page that surfaces all
   `hr.job.stage.config` rows for this stage as an inline-editable
   tree.

> ⚠️ **SUPERSEDED by v17.0.15.0.0.** Both override fields below and the
> resolution-priority chain were removed — `booking_url` now resolves to
> `appointment.invite.book_url` only. The text is kept for historical
> context; do not reintroduce the chain.

**New fields:**

- `hr.job.stage.config.default_meeting_url` (Char) — optional fixed
  meeting room for everyone on this (job, stage). Recruiters paste a
  permanent Google Meet / Zoom URL; the invite email uses it instead
  of an Appointments-minted link.
- `hr.applicant.manual_meeting_url` (Char, `copy=False`) — per-applicant
  override. Wins over both `default_meeting_url` and the Appointments
  link. Cleared on copy to avoid stale links on duplicated applicants.

**Resolution priority for `booking_url` (read this when changing the
chain):**

```
applicant.manual_meeting_url
  → hr.job.stage.config.default_meeting_url (for the current Call Stage)
  → appointment.invite.book_url
  → ''
```

The same chain is honoured by:
- `_compute_booking_url` (cockpit field; readable from templates via
  `object.booking_url`).
- `action_send_invite_email` (passes `applicant.booking_url` into the
  `booking_url` context key for legacy templates).
- `_track_template` (automatic stage-tracked sends).

`_compute_call_status` was updated so an override URL produces
`link_ready` even when no `appointment.invite` exists. `booked` still
requires an `appointment.invite` + `calendar.event`, because only the
Appointments flow produces those — recruiters using fixed rooms must
mark `attended` / `no_show` manually after the call.

**Mint-skip contract:** when an override URL is present,
`action_send_invite_email` and `_track_template` deliberately skip
`_get_or_create_booking_invite`. Creating an unused invite would
pollute the candidate's history and confuse the cockpit. Never re-add
an unconditional mint; if you need a status state for "override URL
ready", reuse `link_ready` and gate behaviour on
`call_outcome` instead.

**Inherited form contract:** `view_hr_recruitment_stage_form_call_inherit`
appends the page via `xpath="//sheet"` `position="inside"`. The
existing native form has no notebook, so we add one. If Odoo Recruitment
adds a notebook in a future minor release, update the xpath to insert a
page rather than the wrapping notebook to avoid duplicates.

## v17.0.4.0.0 — Etap 4: polish & power-user UX

Implements Etap 4 of `docs/call_stage_improvement_plan.md`. Quality-of-life
additions on top of the cockpit; no model rewrites.

**What was added:**

- **Bulk server action** `action_server_send_call_invite_bulk` —
  bound to `hr.applicant` tree+kanban. Filters out applicants whose
  `call_scheduling_visible` is False so a recruiter selecting "All" in
  kanban never accidentally hits applicants from jobs without a Call
  Stage. Re-uses the per-applicant idempotent
  `action_send_invite_email`.
- **Kanban badge** — `call_status` rendered as a coloured pill next to
  the activity widget. Six states with distinct icons (no_link /
  link_ready / sent / booked / attended / no_show). Visible only when
  `call_scheduling_visible`.
- **Preview Email button** on the Call Stage config row — calls
  `action_preview_call_invite`, which renders the assigned template
  against a real sample applicant (or a dummy URL when none exist) and
  surfaces the rendered HTML via a sticky client notification.
- **Candidate timezone field** `candidate_tz` (computed from
  `partner_id.tz`), surfaced in the Call Scheduling section next to the
  booking URL.
- **Breadcrumb action** `action_open_call_stage_config` — button on the
  applicant's Call Scheduling section that jumps to the
  `hr.job.stage.config` row driving the flow.

**No migration needed** — all additions are field/method/view records.
Manifest data list grew by one file (`views/hr_applicant_actions.xml`).

**Bulk action filter contract:** the server action MUST filter via
`call_scheduling_visible` before fanning out send-email. Removing that
filter would attempt to mint invites for jobs that have no Call Stage
configured, raising UserError mid-loop and leaving the bulk operation
half-applied.

## Where booking_url comes from

`appointment.invite.book_url` is a computed field already provided by
Odoo Appointments (`appointment/models/appointment_invite.py:28`). We
never synthesise a URL — we read `book_url` from the invite. The short
URL it returns is itself a redirect that appends the access token, so
candidate identity flows through automatically.

## Booking-form prefill & lock (v17.0.8.0.0)

The public booking form (Name / Email / Phone) is pre-filled from the
candidate card and the present fields are locked, so a candidate never
re-types data we already hold.

**No new token.** The `invite_token` already carried through every
booking step *is* `appointment.invite.access_token`, and the invite is
already linked to the applicant via `applicant_id` (shipped by
`appointment_hr_recruitment`). We resolve applicant from token — no new
field, model, or token.

**Two controller overrides** (`controllers/main.py`,
`CallStageAppointmentController(AppointmentController)`):

- **GET `/appointment/<id>/info`** — calls `super()`, then mutates the
  rendered `response.qcontext` (a mutable dict, per `odoo/http.py`):
  overwrites `partner_data` name/email/phone with card values and injects
  `recruitment_locked_fields = {'name'|'email'|'phone': bool}`. The key is
  always set (defaulted to `{}`) so the template inherit is safe on the
  native path too.
- **POST `/appointment/<id>/submit`** — *before* `super()`, present-on-card
  fields overwrite the submitted `name`/`phone`/`email` (the real lock —
  client `readonly` is only a hint); empty-on-card fields are collected and,
  *after* a successful booking, written back to the applicant
  (`partner_name` / `email_from` / `partner_phone`). Write-back is skipped on
  `state=failed-*` redirects.

**Attendee resolution** (`_get_customer_partner`, since v17.0.18.1.1): for a
recruitment booking we return the candidate's own `applicant.partner_id`
(sudo) instead of letting the native submit fall back to an arbitrary
`res.partner.search([('email','=like', email)], limit=1)`. Two reasons: (1)
it's the correct attendee; (2) the native guard at `appointment.py:686`
raises **"Please connect to book the appointment"** whenever the email-matched
partner owns a user account — which blocked legitimate, token-proven public
bookings whose candidate email collided with a partner that had a user. The
candidate contact is created userless by `_ensure_partner_for_booking`, so
`customer.user_ids` is empty and the guard is skipped. Logged-in and
non-recruitment bookings fall through to `super()` untouched. *Known edge:* an
applicant manually linked to a partner that owns a user would still trip the
guard.

**Field map contract** (`_call_stage_field_map`, single source for both GET
lock flags and POST enforcement so "shown read-only" ⇔ "forced on server"):

- name ← `partner_name` **only** (never `name`, which is the application
  subject). Empty `partner_name` ⇒ editable + write-back.
- email ← `email_from`.
- phone ← `partner_phone` or `partner_mobile`; write-back targets
  `partner_phone`.

**Template** (`views/appointment_templates.xml`) inherits
`appointment.appointment_form` with `position="attributes"` adding
`t-att-readonly` driven by `recruitment_locked_fields`. Uses `readonly`
(submits) not `disabled` (does not submit). Optional SCSS
(`o_call_stage_locked_field`) only adds a muted background.

**Pass-through guarantee:** no token / unknown token / invite without an
applicant ⇒ every override delegates straight to `super()` and the native
public booking flow is byte-for-byte unchanged.

**Security/PII note:** the `access_token` link is the capability — anyone
holding the (candidate-personal, emailed) link sees the prefilled
name/email/phone and can book. This is a small escalation over native
(which prefills only for logged-in users) but the link is already private
to the candidate. All applicant reads/writes use `sudo()` scoped to the
token-resolved applicant; the request stays `auth="public"`.

## Calendar-page candidate header + side availability (v17.0.9.0.0)

Improves the *first* (slot-selection / calendar) page of a recruitment
booking. Native Odoo only collects the attendee identity on the second
("Add more details about you") step; for a recruitment booking the
candidate is already known, so we surface it earlier and tidy the layout.

**Third controller override** (`_get_appointment_type_page_view`, the
documented override point that builds `appointment.appointment_info`'s
`render_params`): calls `super()`, then mutates `response.qcontext` to add —
only when the token resolves to an applicant —

- `recruitment_booking = True` (defaulted to `False` for the native path),
- `recruitment_candidate_name` ← `_call_stage_field_map`'s `name`,
- `recruitment_candidate_email` ← its `email`.

`recruitment_booking` is also set on the GET `/info` qcontext (same default)
purely so any future form-step inherit can branch on it safely.

**Template** (`views/appointment_templates.xml`,
`appointment_info_recruitment_header` inheriting `appointment.appointment_info`):

- Inserts an `o_call_stage_candidate_banner` (name in large bold, email
  below) right after the "Select a date & time" heading, above the calendar.
  Gated on `recruitment_booking` — invisible on native pages.
- Flips the calendar / availability split from the `xl` to the `lg`
  breakpoint **for recruitment bookings only** so the available-hours list
  sits *beside* the calendar on more screen widths instead of dropping below
  it. The static `col-xl-8` / `col-xl-4` classes are kept verbatim on the
  native path via the `recruitment_booking` ternary.

**Phone is prefilled, not removed.** Earlier discussion considered dropping
the phone field (Google-Meet-only interviews); the decision was instead to
keep autofilling it like name/email — handled by the unchanged
`_call_stage_field_map` phone mapping above. The banner intentionally shows
**name + email only**.

**SCSS** (`appointment_call_stage.scss`): `.o_call_stage_candidate_banner`
styling only (tertiary background, primary left border, large name).

**Pass-through guarantee** still holds: no/unknown token ⇒ `recruitment_booking`
stays `False`, the banner is not rendered, and the breakpoints are the native
`xl` — the page is byte-for-byte unchanged.

## Skip the "details" step when the card is complete (v17.0.12.0.0)

Design doc: [`docs/skip_details_step_plan.md`](../docs/skip_details_step_plan.md).

For a recruitment booking where the card already holds the **full identity**
(name+email+phone all locked) **and** the appointment type asks nothing else,
the second ("Add more details about you") step only re-displays data we have.
So the GET `/info` override now **skips it and confirms immediately**.

**Predicate** — `_call_stage_should_skip_details(applicant, appointment_type,
locked)` returns `True` only when ALL hold: applicant resolved; `name`, `email`
and `phone` all locked; **`messenger` locked** (a contact already on the card —
see v17.0.13.0.0); `not appointment_type.question_ids`; `not
appointment_type.allow_guests`. Any miss ⇒ render the read-only form (the
v17.0.8.0.0 behaviour) unchanged. Non-recruitment bookings are never affected.

**Mechanism** — the slot click is a full browser navigation to GET
`/appointment/<id>/info` (`document.location` in
`appointment_select_appointment_slot.js`), not AJAX, so a redirect from that
handler is followed. In `appointment_type_id_form`, after computing `locked`,
when the predicate is true we call `self.appointment_form_submit(...)` directly
with the card's name/phone/email + slot params and **return its redirect** (the
`/calendar/view/<token>` confirmation page). `super().appointment_type_id_form`
is still called first, preserving slot validation (`NotFound`) and `partner_data`.

**Why safe** — identity comes from the card and is already enforced server-side
by our `appointment_form_submit` override; `appointment_form_submit` re-validates
the slot (capacity/staff races ⇒ `state=failed-*` redirect, same as the native
Confirm button); CSRF is moot (in-process call, not HTTP routing). No template
or banner change — the calendar banner (v17.0.9.0.0) still shows who it is for.

## Messenger contact capture (v17.0.13.0.0)

Design doc: [`docs/messenger_contact_plan.md`](../docs/messenger_contact_plan.md).

Captures one messenger contact per candidate (Telegram **or** WhatsApp, never
both) for the call. Genie auto-prefill is **not** built yet — the fields are
plain, writable, and ready for it.

**New fields on `hr.applicant`** (file `models/hr_applicant.py`):
- `messenger_type` (Selection `telegram`/`whatsapp`, `copy=False`) — the kind.
- `messenger_value` (Char, `copy=False`) — the contact. WhatsApp ⇒ a phone
  number; Telegram ⇒ a username/handle. "Present" ≡ `messenger_value` truthy;
  a type with no value is treated as empty. No default, no compute, no inverse.

Surfaced in a **Messenger contact** group on the applicant form's *Call
Scheduling* page (`views/hr_applicant_views.xml`).

**Booking form** (`views/appointment_templates.xml`, gated on
`recruitment_booking`): a row after Phone with a two-button **switch**
(Telegram / WhatsApp, Bootstrap `btn-check` radios — no JS) + a single value
input. When the card already holds a contact it is pre-filled, the switch is
disabled with the kind pre-selected (a hidden `messenger_type` input carries it
into the POST since disabled radios don't submit), and the value is read-only —
the same lock as name/email/phone. When empty on the card the switch + value are
`required`, so the candidate must pick a messenger and type a contact.

**Controller** (`controllers/main.py`):
- `_call_stage_messenger_from_card(applicant)` → `(type, value)`.
- GET `appointment_type_id_form` injects `partner_data['messenger_type'/
  'messenger_value']` + `recruitment_locked_fields['messenger']`.
- POST `appointment_form_submit` reads `messenger_type`/`messenger_value` from
  `**kwargs` (the native submit ignores them, like `invite_token`); **enforces**
  the card value when present and **writes back** an empty-on-card contact only
  as a complete, valid `(type ∈ {telegram, whatsapp}, value)` pair, guarded by
  the existing `_call_stage_is_failed_redirect` success check.

**Required is a client hint** — consistent with the rest of the module the
server never hard-rejects a tampered/empty POST: the booking still confirms,
the messenger simply isn't written. Hard-block (re-render with an error) is a
documented future option, deliberately not taken to preserve the pass-through
contract.

No ACL change (fields on an existing model) and no migration (new nullable
columns; bump-only, like v8–v12).

## Recruiter photo on the booking page (v17.0.14.0.0)

On the booking page's right-hand "Meeting details" column, the appointment-type
cover image (a generic book/placeholder) is swapped for the **assigned
recruiter's photo**, so the candidate sees who they will talk to.

**Template** (`views/appointment_templates.xml`,
`appointment_meeting_details_recruiter_avatar`): inherits
`appointment.appointment_meeting_details` and `position="replace"`s the
`.o_appointment_details_type_cover` node with a conditional:
- recruiter known (`staff_user`, or the single `staff_user_ids` when none is
  picked yet) **and** `recruitment_booking` ⇒ a square avatar div backed by the
  public `/appointment/<id>/avatar?user_id=<uid>` route;
- otherwise ⇒ the stock `website.record_cover` (so non-recruitment pages and
  ambiguous multi-recruiter types are byte-for-byte unchanged).

`recruitment_booking` and `staff_user` are always defined where this template
renders (the call-stage controller `setdefault`s the flag on both the date and
form pages; `appointment_details_column` always `t-set`s `staff_user`).

**Config side** (`models/hr_job_stage_config.py`,
`_show_recruiter_avatar_on_booking_type`, called from `create`/`write` next to
`_sync_recruiter_staff_users`): forces the Call Stage booking type's
`avatars_display` to `'show'`. The avatar route only serves a real picture when
`avatars_display == 'show'` (else a placeholder), so this guarantees the photo
appears with zero recruiter configuration. The field is a stored compute keyed
only on `category`, so the manual `'show'` survives recompute.

## Additional interviewers (v17.0.16.0.0)

Lets the recruiter add **another internal user** (e.g. the CEO or hiring
manager) to a candidate's call. That person joins the booked call beside the
recruiter and candidate, receives the calendar invite carrying the Google Meet
link, and their **photo is shown to the candidate on the public booking page**.

**Two places to choose them (both supported):**

- **Per Call Stage default** — `hr.job.stage.config.interviewer_user_ids`
  (`Many2many('res.users')`, rel `hr_job_stage_config_interviewer_user_rel`,
  internal-only domain). Shown on the stage config form under the call-stage
  fields.
- **Per candidate** — `hr.applicant.call_interviewer_user_ids`
  (`Many2many('res.users')`, rel `hr_applicant_call_interviewer_user_rel`,
  `copy=False`). Shown on the applicant's *Call Scheduling* page.

**Seeding & source of truth.** When a candidate *transitions into* a Call
Stage, `hr.applicant.write` → `_call_stage_seed_interviewers` copies the
stage's `interviewer_user_ids` into the applicant's
`call_interviewer_user_ids`. Two guards make it predictable:

- the seed fires only on an **actual stage change** (`old != new`, captured
  before `super()`), so a same-value rewrite that merely carries `stage_id`
  never reseeds — a recruiter's deliberate clear survives any later save; and
- it seeds only when the applicant's exact current stage is a Call Stage AND
  `call_interviewer_user_ids` is empty, so an already-curated list is never
  stomped.

(A genuine move-away-and-back into the stage with an empty list does reseed —
treated as a fresh start, which is the expected behaviour.)
`action_generate_booking_link` re-runs the same seed as a backstop for
applicants already sitting on a Call Stage before upgrade. From then on
`call_interviewer_user_ids` is the **single source of truth** — no union with
the stage default at booking time, so a removed interviewer stays removed.

**Not staff.** Interviewers are deliberately kept OUT of the appointment type's
`staff_user_ids`: they must not gate slot availability nor become bookable
operators. This is the key distinction from `recruiter_user_ids`.

**Attendee injection** (`models/calendar_event.py`,
`_call_stage_add_interviewers`, called in the `create` post-create loop next to
enrich/auto-advance): for an applicant-linked booking event, each interviewer's
`partner_id` is added to `event.partner_ids` via `(4, id)` (idempotent). Odoo
then creates the `calendar.attendee` rows and sends the standard invitation —
already carrying the Meet link in `videocall_location` — so nothing is minted
separately. Reschedules that spawn a new event re-run through `create`, so the
panel is preserved; a reschedule that writes the same event keeps its existing
attendees.

**Photo on the booking page.** The native `/appointment/<id>/avatar` route only
serves users in `staff_user_ids`, so it cannot serve an interviewer. A
dedicated public route `/call_stage/interviewer/<user_id>/avatar`
(`controllers/main.py`, `call_stage_interviewer_avatar`) mirrors the native
route's public+sudo pattern with its own access gate: it serves the avatar only
when the user is configured as an interviewer somewhere (any
`hr.job.stage.config.interviewer_user_ids` **or** any
`hr.applicant.call_interviewer_user_ids`); otherwise the generic placeholder.
The controller injects `recruitment_interviewers`
(`= applicant.call_interviewer_user_ids`) into the booking qcontext on both the
date and form pages (`setdefault`-ed to empty so non-recruitment pages are
unchanged). Template `appointment_meeting_details_interviewers`
(`views/appointment_templates.xml`) appends a *"You will also meet"* panel
after the meeting-details block, one row per interviewer (photo + name +
position), styled by `.o_call_stage_interviewers` in the frontend SCSS.

No new model ⇒ no ACL change. No migration (new nullable m2m relation tables;
bump-only).

**Interviewer position/job title (v17.0.17.1.0).** The panel row shows each
interviewer's job title under their name. The value lives on the interviewer's
`hr.employee` record, which the **public** candidate rendering the page cannot
read — so it is resolved server-side under `sudo` in
`_call_stage_inject_panel_context` and passed pre-computed as
`recruitment_interviewer_positions` (`{user_id: title}`); the template never
touches `hr.employee`. Source priority per interviewer:
`employee.job_title` → `employee.job_id.name` → `partner_id.function` (legacy
fallback), so a value shows whichever field HR actually filled. The template
reads `recruitment_interviewer_positions.get(interviewer.id)` (was a direct
`t-field="interviewer.partner_id.function"`, which stayed blank because the
partner *Function* field is rarely set). The key is `setdefault`-ed to `{}` on
both injection points so non-recruitment pages are unchanged. The existing
`.o_call_stage_interviewer_fct:empty` SCSS rule still hides the line when the
position resolves empty.

## Booking-page info panel — job/company + "What to expect" (v17.0.17.0.0)

Makes the right-hand "Meeting details" column of the public booking page more
informative (Calendly-style), **recruitment bookings only** — every gate is
`recruitment_booking`, so non-recruitment pages are byte-for-byte unchanged.

**New field.** `hr.job.stage.config.what_to_expect` (`fields.Text`) — a free
text the recruiter fills per (job, stage); one line = one bullet. Exposed on
`email_page` after `interviewer_user_ids` (`invisible="not is_call_stage"`).
Purely informational; never touches slot availability or the booking flow. No
model added ⇒ no ACL/migration (new nullable column, bump-only).

**Controller** (`controllers/main.py`, `_call_stage_inject_panel_context`).
A shared helper injects three keys into the booking qcontext on **both** the
date page (`_get_appointment_type_page_view`) and the slot/form page
(`appointment_type_id_form`), each `setdefault`-ed to empty on the native path:

* `recruitment_job_name` = `applicant.job_id.name`
* `recruitment_company_name` = `applicant.company_id.name` (falls back to
  `job_id.company_id.name`)
* `recruitment_what_to_expect` = the config's `what_to_expect` **split on
  newlines, blank lines stripped** → a list the template renders as bullets.
  The config is resolved with `applicant._get_current_call_config()` (same
  helper as the booking URL; handles the "already advanced to Call Booked"
  fallback). Empty list ⇒ the panel is hidden.

**Templates** (`views/appointment_templates.xml`, both inheriting
`appointment.appointment_meeting_details`):

* `appointment_meeting_details_recruiter_avatar` gains a second xpath that adds
  a muted `job · company` line right after the appointment-type name
  (`//h5[hasclass('mb-1')]`), so the candidate sees which role/company the call
  is for.
* `appointment_meeting_details_what_to_expect` appends a *"What to expect"*
  bullet list after the same `flex-column gap-1` details block the interviewers
  panel uses. Styled by `.o_call_stage_what_to_expect` in the frontend SCSS
  (smaller font, roomier line-height).

**Deliberately NOT added: reschedule/cancel/job links on the confirmation
page.** Considered (the original spec's "step 3c") and dropped: the
`appointment_validated` page is rendered by the stock route and carries no
`recruitment_booking` flag (the block would be dead), `appointment.invite` has
no `cancel_url`/`reschedule_url`, the native page already shows a
"Cancel/Reschedule" button, and **`jito_appointment_emails` already ships
Reschedule + Cancel buttons** (via `/calendar/<token>/cancel`) in the booking
emails — so adding them again would duplicate existing functionality.

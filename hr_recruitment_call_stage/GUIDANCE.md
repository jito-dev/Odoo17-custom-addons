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
3. An applicant with `manual_meeting_url` set, sent via
   `action_send_invite_email`, produces a queued `mail.mail` whose
   body contains the pasted URL — confirms the live render path off a
   fresh body.

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

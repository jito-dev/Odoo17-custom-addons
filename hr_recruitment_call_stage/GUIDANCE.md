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

## v17.0.28.1.0 — a type created by a migration had no cover properties (500)

**Symptom.** Opening the appointment type created by the v17.0.28.0.0 pass gave
`500: Internal Server Error`, from `website.record_cover`:

```
TypeError: the JSON object must be str, bytes or bytearray, not bool
Node: <t t-set="_cp" t-value="_cp or json.loads(_record.cover_properties)"/>
```

**Cause.** `website_appointment` bolts `website.cover_properties.mixin` (and the
published/website fields) onto `appointment.type`. This module does not depend on
it, and modules are loaded in dependency order — a model grows as they load. When
`hr_recruitment_call_stage`'s post-migrate runs, those fields are not necessarily
in the registry yet, so a record created there misses them entirely and
`cover_properties` lands NULL. Nothing complains until the website template tries
to parse it.

On `odoo_dev` exactly one row was affected — id 22, the type the migration had
just created; every other appointment type carried its JSON.

**Fix, in two places.**

* `17.0.28.0.0/post-migrate.py` now copies `cover_properties`, `is_published` and
  `website_id` from the source type **in SQL**, straight after the ORM copy. SQL
  sidesteps the registry: the columns are on the table whether or not the fields
  are loaded. With a complete registry the ORM copy already carried them and the
  statement rewrites identical values. So no database still to upgrade can
  produce a broken type.
* `17.0.28.1.0/post-migrate.py` repairs the rows already written, giving any
  `appointment.type` with a NULL `cover_properties` the mixin's default. Also
  SQL, for the same reason, with the default kept as a literal.

**The lesson worth keeping:** creating records in a post-migrate means creating
them against a half-built registry. Anything a module you do not depend on adds
to that model may simply not be there. Copy such columns in SQL, or do not create
the record in a migration at all.

`test_interviewer_retirement.py` asserts the created type carries cover
properties whenever the field exists.

## v17.0.28.0.0 — the appointment type is the only answer to "who runs the call"

`call_staff_user_ids` ("Interviewer") is **gone**, together with the pool growth,
the assignability constraint, the type-change prune and the invite narrowing.

### Why

Who runs a call was described in two places that had to agree: the appointment
type's `staff_user_ids`, and the stage's subset of it. They could not be kept in
agreement, because the subset is applied **exactly once** — when the candidate's
`appointment.invite` is minted — and never revisited. Everything that moves
afterwards degrades it into "anyone free", quietly. Reproduced on `odoo_dev`:

| What happened | What the system did |
|---|---|
| somebody removed the pinned person from the type | `_call_invite_values() → {}`: no narrowing at all, while the form still read *"Every call from this stage goes to Ann"* |
| the pinned user was archived | the field reads empty → falls back to the whole staff |
| the Interviewer was changed | applies to new candidates only; anyone already holding a link keeps the old person |
| the type was switched to schedule resources | the constraint never re-runs; narrowing silently disappears |

Two lists, one of them a snapshot. Removing the snapshot removes the whole class
of failure — there is nothing left to keep in step.

### What replaced it

Nothing. The stage picks a type; the type carries its staff, its duration, its
questions. Pointing a stage at a **colleague's** type has been possible since
v17.0.26.0.0 (`security/appointment_security.xml`, read-only on every type), so
no capability is lost by dropping the subset.

One capability is gained. An invite that carries no staff filter puts no
`filter_staff_user_ids` in the booking URL, so the page reads the type's staff on
every request (`appointment/controllers/appointment.py::_get_possible_staff_users`).
**Change who is on the type and every link already in a candidate's inbox
follows** — the third row of the table above is fixed by construction rather than
by a patch.

### The trade, accepted with the customer

Two stages can no longer share one type and route to different people; that needs
two types. Six of the seven types on this database already backed exactly one
stage, so the pattern was in use long before it was the rule.

### The dialog after the change

The type IS the configuration now, so the way into it sits **on its own row** —
and that is simply the many2one's own internal-link arrow. A button was added
there first and then removed: it duplicated the stock arrow, and the stock one
is the better of the two anyway, because it opens the type in a dialog **on top
of** these settings where an `act_window` with `target: current` replaces them.
`action_open_appointment_type` went with it — nothing called it any more.

The foot toolbar itself is **folded** into a native `<details>` ("Check and
preview"). None of Preview / Send test / Booking page / Template / Applicants is
part of configuring a stage — they are ways to go and look at something — and six
buttons sitting open under the settings read as six more decisions. Each carries
a one-line hint on hover. No widget and no JS: the fold survives a form whose
assets failed.

> An earlier revision of this version added an `action_create_booking_type`
> button ("Create an appointment type for this stage"). It was **dropped**: it
> added another layer to a dialog that already nests deeply, and creating a type
> belongs in the Appointments app. Note the consequence, which predates this
> module: `_check_call_stage_has_appointment_type` refuses to save a Call Stage
> with no type, so a stage still cannot be set up before its type exists.

### Renamed / re-aimed

* `call_staff_pool_ids` is now a **visible read-only** field, "Runs the call".
* `call_pool_shared_stages` lists **every** other Call Stage on the type, not
  only those that had left the Interviewer empty. Sharing a type is the only
  coupling left, so it is the only thing the banner needs to say.
* `call_assign_hint` is unchanged and now cannot lie: it reports the type.

### Migration `17.0.28.0.0`

Reads the retired many2many with raw SQL (post-migrate still has the table) and
**preserves what happens today, not what was once intended**:

| Pin | Action |
|---|---|
| equals the type's whole staff | nothing |
| a strict subset | a dedicated type (copy, staff = the pinned people), the stage repointed **and its live invites moved with it** |
| names somebody no longer on the type, or only archived users | nothing — that pin already resolved to "anyone free" |

Invites move because `_get_current_invite` finds an invite by the stage's current
type: leave them behind and every candidate holding a link reads as `no_link` in
the cockpit and gets sent a second one. The candidate sees nothing — `book_url`
resolves through the invite's short code.

On `odoo_dev`: one stage split (`UXUI Design Trainee / Interview with Yarnai`),
one invite moved, `Recruitment test` left untouched for the four stages that
share it.

> `appointment.type.copy()` overwrites `default['name']` unconditionally
> (`appointment_type.py:345`). The name has to be written **after** the copy, in
> both the button and the migration. A test caught this.

### Tests

`test_interviewer_pool_grow.py` → `test_appointment_type_config.py`: the growth
class is gone, the record-rule coverage stays and gains the button.
`test_interviewer_retirement.py` is new and covers the migration, including the
re-run case. Full suite: 0 failed, 0 errors of 211 tests across this module, the
Google Meet bridge and `google_meet_integration`.

## v17.0.27.1.0 — the readiness badge left its own statusbar

The dialog's title sat in a band of empty space. Cause: the `<header>` this
view added held exactly one thing — the readiness badge — and a statusbar is a
full-width element with its own padding and border.

The badge now renders inline with the adaptive title (`Call invite  [Ready to
send]`, `.o_cs_badge` keeps it chip-sized at 11px), and the `<header>` is gone.

Safe to remove: the only other `//header` anchor in this codebase is
`hr_recruitment_fireflies`' "Interview Questions" button, which targets the
`hr.recruitment.stage` form — a different model and view. Verified before
deleting.

Paired with `hr_recruitment_job_stage_config` v17.0.1.6.0, which trims the
shell's sheet/title spacing now that nothing sits above the sheet.

## v17.0.27.0.0 — "Who runs the call" removed; settings dialog re-laid out

**The field that did nothing.** `call_assign_mode` (This person / Anyone free /
Applicant picks) is deleted. Whether the candidate picks a person or Odoo
auto-assigns one is `appointment.type.assign_method` — a field on the TYPE that
this module never wrote. In `_call_invite_values` all three modes produced the
same payload once an interviewer was selected, so `anyone_free` and
`applicant_picks` were literally indistinguishable. Its only real effect was the
`_check_this_person_is_one_person` constraint, which blocked a perfectly normal
two-interviewer setup. Both are gone.

Replaced by `call_assign_hint` — one muted, read-only sentence stating what the
type actually does ("Every call from this stage goes to X." / "The candidate
picks one of the 3, then a free slot of theirs." / "…Odoo assigns that
person."). Reported, not edited: several stages share one type, so a
stage-level control would silently overwrite a sibling's setting.

`_call_invite_values` is now: named interviewers → `specific_resources` pinned
to them; nobody named → `all_assigned_resources` (whole pool).

**Layout.** The dialog had drifted — eight call fields shared the foundation's
two-column Email group, a full-width preview widget and a textarea among them,
and the pool notice was a third stacked alert box.

* Call fields moved out of the Email group into three titled sections, in the
  order a recruiter thinks: **Who runs the call** → **Meeting** → **The
  candidate sees**. The interviewer now comes before the appointment type.
* The availability card and the inline notes render outside any group, so they
  get the full width instead of a grid cell.
* The free-slot counter left the context strip — the availability card already
  says "N slots free".
* The pool-growth notice became a muted line under the Interviewer field,
  where the action that causes it lives.
* `.o_cs_form .o_inner_group .o_field_widget { max-width: 26rem }`, compact
  alerts, and a 3-row "What to expect" textarea.

The DB column `call_assign_mode` is left orphaned on purpose — no migration, no
data worth keeping (every row held the default).

## v17.0.26.0.0 — a recruiter can hand the call to a colleague

**Symptom (prod).** In *Call Stage Settings* a recruiter saw only **their own**
appointment types, and only **themselves** under *Interviewer*. Interviews could
not be assigned to anyone else.

**Two independent causes.**

1. *Appointment type.* Stock rule `appointment.appointment_type_rule_user`
   limits an Appointment User to types they created or staff. Group rules are
   OR-ed and there is no global rule on the model, so the dropdown showed a
   recruiter their own types only.
2. *Interviewer.* `call_staff_user_ids` was domained on the type's pool
   (variant C), and `appointment.type.default_get` seeds `staff_user_ids` with
   its creator alone (`appointment_type.py:33`). Pool of one → dropdown of one.
   The 00-Design-Plan predicted this: *"C degenerates into A while every type
   has a single staff user."*

**Platform constraint that dictates the fix.**
`appointment.invite.staff_user_ids` is domained on
`appointment_type_ids.staff_user_ids` (`appointment_invite.py:53`) — an invite
can only ever **narrow** the type's pool. So "assign anyone" is only reachable
by putting that person **into** the pool.

**Fix.**

* `security/appointment_security.xml` — a **read-only** `ir.rule` giving
  `hr_recruitment.group_hr_recruitment_user` visibility of every appointment
  type. Write / create / unlink stay under the stock rules.
* Both type pickers (config popup + create wizard) gain
  `domain="[('schedule_based_on','=','users'), ('category','in',['punctual','recurring'])]"`
  — the only shapes a recruitment booking can use.
* `call_staff_user_ids` domain becomes `[('share','=',False)]`;
  `_call_grow_staff_pool` LINKs the picked users into the type's
  `staff_user_ids` after `create`/`write`, via `sudo()` (same policy as
  `_show_recruiter_avatar_on_booking_type`). **Union only — never an unlink**,
  so dropping an interviewer here never takes their calendar from another
  stage.
* `call_pool_add_names` / `call_pool_shared_stages` drive an info banner that
  names who will be added and which sibling stages book the whole pool, so
  growing a shared type is an informed act, not a silent side effect.
* `_check_call_staff_within_pool` → `_check_call_staff_assignable`: rejects
  only what growth cannot fix (resource-based types; `anytime` types, capped at
  one person by a stock constraint). The old check would have fired from inside
  `super().write()`, i.e. before the pool could grow.
* `_onchange_booking_type_prune_staff` prunes only for resource-based types;
  otherwise the selection carries over to the new type.

**Not** re-introduced: the v17.0.24.0.0 `_sync_recruiter_staff_users` UNION.
Only interviewers a human explicitly picked are ever added, and nobody is ever
removed.

Covered by `tests/test_interviewer_pool_grow.py`; three pool tests in
`test_call_assign_mode.py` changed semantics deliberately.
Plan: `obsidian/Projects/Call-Stage-Settings-Redesign/01-Interviewer-Assignment-Fix.md`.

## v17.0.25.0.1 — interviewer dropdown was empty for recruiters (AccessError)

**Symptom:** the new *Interviewer* field offered nobody, for most stages.

**Cause.** `call_staff_pool_ids` was a plain `related` on
`booking_appointment_type_id.staff_user_ids`. Stock `appointment` ships the
record rule *"appointment.type: apt user rule"*:

```
['|','|','|', ('create_uid','=',user.id), ('staff_user_ids.id','=',user.id),
              ('staff_user_ids','=',False), ('schedule_based_on','=','resources')]
```

so an Appointment User only sees types they created or are staff on. On prod
data one recruiter could read **2 of 15** types — every stage wired to a
colleague's type raised `AccessError` on the related read, and the web client
surfaced that as an empty dropdown.

Why it had never bitten before: the older `_compute_call_free_slot_count` wraps
its whole body in `except Exception` and silently returns `-1`, so the same
missing access was swallowed. A `related` field has no such shelter.

**Fix.** `call_staff_pool_ids` becomes a compute that reads the type with
`sudo()`, plus a `_call_appointment_type_sudo()` helper used by every other
derived read (`_call_effective_staff`, the two constraints, the `write` prune,
both warning/preview computes). *Which users are bookable* is reference data,
not sensitive; the model still cannot write to the pool.

Covered by `TestPoolUnderRecordRules` — a recruiter who cannot read the type
must still see who is bookable.

## v17.0.25.0.0 — "Who runs the call" + live 7-day availability preview

Design doc: `obsidian/Projects/Call-Stage-Settings-Redesign/00-Design-Plan.md`
(variant C, approved 2026-08-25).

### The problem this closes

The Call Stage settings dialog had **no interviewer field at all**. The only
people-shaped field was `interviewer_user_ids` ("Additional interviewers"),
which by design does NOT affect availability — so recruiters could not tell who
would actually run the call, or whether that person had any free time.
Consequence visible in prod data: **one `appointment.type` per vacancy**
(15 types, one staff user each).

### The rule: the pool is the boundary

`appointment.invite.staff_user_ids` carries
`domain="[('id', 'in', suggested_staff_user_ids)]"`, and
`suggested_staff_user_ids` is `related='appointment_type_ids.staff_user_ids'`
(`appointment/models/appointment_invite.py:41-54`).

> **The invite can only NARROW the type's pool, never extend it.**

So: the **appointment type owns the pool**; the stage config **selects a subset**
of it. Picking someone outside the pool raises a `ValidationError` naming them,
instead of being silently dropped by the domain.

Deliberately NOT re-introduced: the `_sync_recruiter_staff_users` UNION removed
in v17.0.24.0.0. Adding a person to the pool stays an explicit act on the
Appointment Type form — this module never writes to `staff_user_ids`.

### New on `hr.job.stage.config` (`models/call_stage_assignment.py`)

| Field | Purpose |
|---|---|
| `call_assign_mode` | `this_person` / `anyone_free` / `applicant_picks` |
| `call_staff_pool_ids` | related to `booking_appointment_type_id.staff_user_ids`; domain source only, never written |
| `call_staff_user_ids` | the chosen subset; empty = whole pool |
| `call_availability_7d` | JSON payload for the preview widget (non-stored) |
| `call_warn_staff_unsynced` / `call_warn_unsynced_names` | interviewer has no Google Calendar connected |
| `call_warn_work_hours_off` | the type does not enforce working hours |

`_call_invite_values()` maps the mode onto stock `appointment.invite`
`resources_choice`; it is applied at the single mint point,
`hr.applicant._get_or_create_booking_invite`.

### Availability preview

`_compute_call_availability_7d` calls
`appointment.type._get_appointment_slots(tz, filter_users=...)` — **the same
method the public booking page uses** — so the grid cannot disagree with what
the candidate sees. Empty days carry a reason: `off` (no window that weekday),
`busy`, `lead_time`, `beyond_horizon`.

**Trust rule.** When any interviewer has not connected their Google Calendar,
busy time may simply be missing from `calendar.event`, so a high count would be
confidently wrong. The payload then carries `trusted: false` and the OWL widget
renders the counter **neutral, never green** — green reads as "verified" and
must not lie.

### Two failures that used to be silent

1. **Unsynced interviewer + `google_meet` type** → the candidate gets an invite
   with **no join link**, and the booking still succeeds.
   (`appointment_google_calendar/models/calendar_event.py:22` sets
   `videocall_redirection = False`; the Meet link is minted by Google during
   `_google_insert` and written back post-sync at `:53`.)
2. **`work_hours_activated = False`** — true on all 14 active types in prod, so
   slots can fall outside working time. Warn only; **not** flipped by this
   module (explicit product decision 2026-08-25).

### Other changes

- `interviewer_user_ids` label → **"Also joins the call"** (the field itself is
  untouched; it still never affects availability).
- Assets: `static/src/js/call_stage_availability.js`,
  `static/src/xml/call_stage_availability.xml`, plus SCSS in
  `call_stage_form.scss` (mode pills restyle the stock horizontal radio widget,
  so a11y and keyboard focus stay intact).

### Not in scope

Merging the 15 per-vacancy appointment types into 3–4 — needs an HR decision.
Until then the pool has one member per type and the subset selection degenerates
to "the one person", which is harmless and needs no migration.

## v17.0.24.19.0 — button-less invite when moving several candidates at once (stale-cache fix)

**Symptom (prod):** moving SEVERAL candidates to the Call Stage in one action
sent them the call-invite email but WITHOUT the "Book a call" button — only the
first candidate in the batch got the button. Same job/appointment-type; purely
intermittent.

**Root cause:** `hr.applicant.booking_url` is a non-stored compute with
`@api.depends('job_id', 'stage_id')` that resolves the applicant's
`appointment.invite` through a **search** — a link Odoo's dependency graph
cannot track. A stage change invalidates `booking_url`, and Odoo recomputes it
in **one batch** for all moved applicants; those whose invite is not minted yet
get `False` cached. `_get_or_create_booking_invite` then created the invite but
left that stale `False` in cache. Because Odoo core `message_post_with_source`
(`mail_thread.py`) posts the tracked template by `template.id` — discarding the
`template.with_context(booking_url=...)` we inject — the body falls back to
`object.booking_url` == stale `False`, and the shipped template's
`t-if="ctx.get('booking_url') or object.booking_url"` drops the button.

The send-time guard did NOT catch it: the guard renders with
`booking_url=invite.book_url` in context (a *different* render path than the
tracked send), so it always saw a button.

**Fix:** `_get_or_create_booking_invite` now calls
`self.invalidate_recordset(['booking_url', 'call_status'])` right after creating
the invite, so the next read (the tracked-send render) recomputes against the
fresh invite. Single choke-point → covers the tracked and manual paths.
(Mirror of what `action_generate_booking_link` already did.) The guard is left
as-is on purpose — it is a template-quality check, not a data-freshness check;
conflating the two would break its contract. Tests:
`tests/test_booking_url_cache_refresh.py` (direct cache-poison + 3-applicant
batch; both fail if the `invalidate_recordset` is removed).

## v17.0.24.18.0 — two buttons on the stage form (final)

Per user preference, the config entry is back on the stage form (stage gear →
**Edit**), now as **two buttons** in a shared `<header>`:

- **"Configure Call Stage"** (this module) → `action_open_call_config_for_job`
  opens the full `hr.job.stage.config` dialog (Call invite + Interview questions
  tabs) for the vacancy in context.
- **"Interview Questions"** (hr_recruitment_fireflies) →
  `action_open_interview_questions_for_job` opens a focused **questions-only**
  dialog (`view_hr_job_stage_config_form_questions_only`); works for ANY stage.

The shared header is an empty `<header>` anchor declared once in
`hr_recruitment_job_stage_config` (the common ancestor), so the two sibling
modules each inject their button with `position="inside" //header` — one
statusbar, never two. Both buttons are gated on `context.get('default_job_id')`
(hidden on the global Settings → Stages form). Both actions return `views` in the
`act_window` dict (required — the button hands the dict straight to the JS action
service, which never runs the loader that would otherwise populate `views`).

This accepts that clicking a button from the stage-form dialog opens the config
as a second dialog. That trade-off was chosen deliberately over the v17.0.24.17.0
gear-dropdown experiment (now reverted).

## v17.0.24.17.0 — gear-menu entry (REVERTED in v17.0.24.18.0)

Experiment: a `kanban_header_config_items` gear-dropdown item
("Call & interview settings") that opened the config directly (one dialog, no
nesting). Reverted in favour of the two on-form buttons above — the JS file
`static/src/js/kanban_stage_config.js` was deleted. The Python
`action_open_call_config_for_job` survives, now bound to the "Configure Call
Stage" button.

## v17.0.24.16.0 — remove nested-dialog entry from the stage form

**Problem.** The kanban stage gear opened the **global** `hr.recruitment.stage`
form, which carried a header button *"Configure Call Stage for This Job"*. That
button opened a **second modal on top** of the stage dialog (`act_window`
`target='new'`) — a nested-dialog anti-pattern: two X's, two Save buttons, and an
Email Template field duplicated between the stage's `template_id` and the config's
per-job `mail_template_id`.

**Why not merge into the stage form.** `hr.recruitment.stage` is one **global**
record shared by every job; `is_call_stage` and all call fields live on
`hr.job.stage.config`, keyed by **(job, stage)**. Embedding per-job editing into
the global form (job selector + inline config) is either infeasible or unsafe in
Odoo 17 (no inline x2many *form* render mode; writable-related through a
non-stored pointer silently drops writes; a stored pointer on the shared stage
row causes multi-user clobber). See
[`docs/plan_call_stage_form_merge.md`](docs/plan_call_stage_form_merge.md) for the
full design consilium.

**Change (this version).** Removed the button, its action
`action_configure_call_stage_for_job`, the `is_call_booked_companion_for_job`
field/compute, and the whole inherited view
`view_hr_recruitment_stage_form_call_inherit`
(`views/hr_recruitment_stage_views.xml` deleted). The global stage form now edits
only stage definition. **Per-job call config is reached as a single top-level
dialog** via **Job form → Stages tab → click the stage row** (opens the
`hr.job.stage.config` form directly) or the applicant's **"Open Stage
Configuration"** button. The kanban stage gear was intentionally left editing the
global stage definition (redirecting it needs custom OWL/JS). Interview questions
(Fireflies) remain available on the config form for **any** stage, call or not.

## v17.0.24.15.0 — Call Stage Settings dialog: compact redesign

Rides the foundation shell redesign (`hr_recruitment_job_stage_config`
v17.0.1.4.0). Pure view/asset change — **no model or business-logic edits**;
the `@api.constrains` save-gate and `_compute_call_readiness` are untouched.

- **One status indicator.** Kept the header `call_readiness_state` **badge**
  only. Removed the green "Ready to send" body banner and the "Wired to" chip
  block — both merely repeated the ready state. The danger/warning alerts stay:
  they surface *only* on a problem and carry the actionable fix-list.
- **Adaptive title.** The shell's "Stage settings" title flips to **"Call
  invite"** when `is_call_stage` (xpath on the `stage_title_default` span, so
  the foundation form stays valid when this module is absent).
- **Density.** Removed the heavy smart-button box; the free-slot count is folded
  into the shell's muted context strip. Every secondary action (Preview / Send
  test / Booking page / open Template / open Appointment / Applicants) is
  regrouped into one compact `.o_cs_actions` button row at the foot of the Email
  page — **nothing deleted**, only de-weighted and moved off the header.
- New asset `static/src/scss/call_stage_form.scss` styles `.o_cs_actions`.

## v17.0.24.9.0 — Call Scheduling tab on the candidate card: UX refresh

View-only redesign of the `Call Scheduling` page on the `hr.applicant` form
(`views/hr_applicant_views.xml`); no model/behaviour changes here. Drivers were
four recruiter complaints about that block:

- **Action buttons moved to the TOP of the tab** in a `div.o_row` action bar.
  They previously sat in a bottom `oe_button_box` — the wrong semantic (that
  class is for top-of-form stat buttons) and buried below the fields.
- **`call_outcome` is now read-only.** The `Mark Attended` / `Mark No-show`
  buttons are the single edit path (they also post chatter + schedule the
  no-show follow-up). To preserve correction now that the dropdown is locked,
  each outcome button stays visible in the OPPOSITE terminal state — see the
  bridge view override (v17.0.1.8.0) which extends the `invisible` to
  `not in ('booked','rescheduled','no_show')` (attended) /
  `('booked','rescheduled','attended')` (no-show).
- **"Additional interviewers" → "Joins this call"**, rendered with
  `many2many_avatar_user` (avatars) instead of `many2many_tags` (text), to
  match native recruitment and the photos the candidate sees on the booking
  page. A muted caption disambiguates it from the job-wide native
  **Interviewers** panel at the top of the card. The field
  (`call_interviewer_user_ids`) and its booking-time semantics are unchanged.

NB for future edits: the Google-Meet bridge view xpaths still rely on the page's
**first `<group>` child** being the Status/Booking block (it inserts the Meeting
group after it) and on `field[@name='call_outcome']` existing (it inserts
`call_booked_start` after it). Keep both anchors intact.

## v17.0.24.13.0 — call OUTCOME (attended/no-show) is per-call-stage too

v24.12 scoped `booked`/`sent` to the current Call Stage, but `call_outcome`
(attended/no-show) was still a per-applicant field checked FIRST in
`_compute_call_status` — so marking the first call attended froze the chip on
`attended` for every later Call Stage (the booked-scoping never ran). It is a
100% manual recruiter action (Mark Attended / Mark No-show buttons; no cron).

Fix: `call_outcome` now lives on the **booked `calendar.event`** (one verdict
per call). On `hr.applicant` it became a **computed, read-only mirror**
(`_compute_call_outcome`) of the call relevant to the CURRENT stage
(`_current_call_event_for_outcome`: current-stage booking when on a Call Stage,
else job-wide). `_compute_call_status` reads attended/no_show from that same
event. The Mark buttons set it on the event and **require a booked call** (raise
otherwise; they are only shown when `booked`). Migration `17.0.24.13.0/post-migrate.py`
carries existing applicant outcomes onto each candidate's most recent booked
event. Bridge `hr_recruitment_call_stage_google_meet` still reads
`applicant.call_outcome` (now the computed mirror) — unchanged. Tests:
`test_outcome_is_per_call_stage`, `test_mark_attended_requires_a_booked_call`,
updated `test_mark_attended_and_no_show`.

## v17.0.24.12.0 — cockpit chip is per-call-stage (booked no longer sticks)

Bug: a booking on an EARLIER Call Stage kept the chip on `booked` after the
candidate was moved to a LATER Call Stage where a fresh link was sent — because
`_get_booked_call_event` searched job-wide across every Call Stage type, and the
`sent` marker was per-applicant (and only set by the MANUAL send, never the
auto-send on stage entry).

Fix (`hr_applicant.py`):
- `_compute_call_status` now scopes detection to the CURRENT stage when the
  applicant is **on a Call Stage** (`_is_on_call_stage`): `booked` is resolved
  only against that stage's appointment type (`_get_booked_call_event(appt_types=…)`),
  so an earlier stage's booking no longer masks the new stage's status. When the
  applicant is NOT on a Call Stage (the auto-advanced **Call Booked** stage and
  later), the job-wide fallback is kept — preserving the v17.0.24.7.0 fix.
- `sent` is now **per-invite**: `_post_call_invite_sent_marker(invite)` tags the
  chatter note with `call-invite-sent-marker:invite=<id>;` and is called by BOTH
  the manual send AND the auto-send (`_track_template`) — so stage-entry
  auto-sends finally register as `sent`. `_has_call_invite_sent_marker(invite)`
  checks that invite, with a legacy fallback to the old bare marker.

Tests: `test_etap3_cockpit.py` — `test_booked_event_scoping_by_appt_type`,
`test_booked_does_not_stick_when_moved_to_other_call_stage`,
`test_sent_marker_is_per_invite`, `test_legacy_bare_sent_marker_still_counts`.

## v17.0.24.11.0 — candidate reaches Google from the FIRST push (recruiter-on-behalf)

Bug: a recruiter booking on a candidate's behalf left the candidate off the
**Google** event (only the recruiter was a guest → candidate got no invite, the
call never reached their Google Calendar). Root cause is the sync ordering in
`google_calendar/models/google_sync.py`: for a Google-synced booker,
`_google_insert` runs **synchronously inside `super().create()`** with only the
booker as guest; the candidate was added a step later in our post-create loop and
relied on the immediate `_google_patch` (`timeout=3`) — which, if slow/failed,
left the candidate off Google entirely.

Fix (`calendar_event.py`): `create()` now injects the candidate (+ seeded
interviewers) into `vals['partner_ids']` **before** `super().create()` via
`_call_stage_collect_booking_attendee_ids`, so the first `_google_insert` already
carries them as guests (`sendUpdates=all`). The post-create
`_call_stage_ensure_candidate_attendee` stays as an idempotent safety net for the
public-portal path and reschedules. Tests:
`test_collect_booking_attendee_ids*` in `test_candidate_attendee.py`.

## v17.0.24.10.0 — "Send test email" works without a candidate

`action_send_test_email` previously raised *"There is no candidate on this
job to render a test against"* when the job had no applicant. Now:

- the recruiter-recipient and template checks run first;
- when a real candidate exists → unchanged (mints the real invite, renders
  against it);
- when none exists → it renders against an **ephemeral `hr.applicant`** created
  inside `self.env.cr.savepoint()` and **always rolled back** (via the
  module-level `_RollbackTestEmail` sentinel). `force_send=True` delivers over
  SMTP *before* the rollback, so the recruiter still receives the styled
  `[TEST]` email while no test record / booking invite / `mail.mail` row is
  persisted. A placeholder booking URL (`_TEST_EMAIL_SAMPLE_URL`) makes the
  "Book a call" button render. `tracking_disable=True` on the temp create
  prevents the stage-entry hooks (and any auto-email) from firing.

Both paths share `_call_stage_dispatch_test_email`, which always forces
`email_to` to the current user — a test never reaches a real candidate.

## v17.0.24.8.0 — Email-preview "Back to settings" + explicit per-job override

Two recruiter-reported papercuts on the Call Stage Settings dialog:

- **Preview dialog had no way back, and "Close" could take the config with
  it.** `action_preview_email` opens the `hr.call.stage.preview` form as a
  dialog *on top of* the config dialog; with only a `special="cancel"` Close
  button, Odoo's dialog-on-dialog stacking could collapse the whole stack.
  Fix: the preview footer now has a primary **"Back to settings"**
  (`hr.call.stage.preview.action_back_to_config`,
  `models/call_stage_preview.py`) that returns an `act_window` re-opening the
  originating `hr.job.stage.config` form (`target='new'`). Routing through the
  action service removes the preview dialog as it opens the config form, so the
  recruiter reliably lands back on a working settings form. "Close" is kept as
  the secondary button. Empty `config_id` → returns `act_window_close` (never
  crashes).
- **"Email Template (per-job override)" looked empty on older Call Stages.**
  The override (`mail_template_id`) is auto-filled the moment a Call Stage is
  enabled (create / write / onchange), but rows enabled before that auto-fill
  landed kept an empty override and silently used the shipped fallback. New
  migration `migrations/17.0.24.8.0/post-migrate.py` backfills the shipped
  `mail_template_call_invite_generic` into every `is_call_stage=TRUE` row whose
  `mail_template_id IS NULL`. Visibility-only: override and fallback are the
  same template, so the email that actually sends is unchanged. Explicit
  recruiter picks are never overwritten.

Tests: `tests/test_call_stage_settings_ui.py` —
`test_preview_back_to_config_reopens_settings`,
`test_preview_back_to_config_without_config_just_closes`,
`test_override_template_autofilled_on_enable`.

## v17.0.24.6.0 — Robust email-template auto-pull on the Call Stage config

Fixes the config-form symptom "the email template stops auto-filling when I tick
*This is a Call Stage*". See `docs/template_autofill_improvement_plan.md`.

**Root cause.** A long-standing asymmetry (both paths from commit "Calendar
link", unchanged since — NOT a v24.x regression): `create()` guarded the
auto-fill with `not vals.get('mail_template_id')` (robust to falsy), but
`write()` used `'mail_template_id' not in vals` (skips whenever the key is
present, even `False`). The web client sends `mail_template_id: False` when the
field is left empty → the `write()` guard suppressed the fill. NB: the candidate
email was never broken — `_resolve_call_invite_template` already falls back to
the shipped template; the bug was purely the empty config-form field.

**Fix (A).** `write()` now uses `if not vals.get('mail_template_id')` — skip the
auto-fill ONLY when an explicit **truthy** template is set in the same write; a
falsy value still injects the shipped default. Mirrors `create()`.

**Fix (B).** New `@api.onchange('is_call_stage')`
`_onchange_is_call_stage_autofill_template` on the config model (mirrors the
create-wizard onchange): ticking the toggle pre-fills the shipped template
**live** in the form, before save. Both fills only touch an EMPTY field — a
recruiter override is never overwritten.

No schema/data change ⇒ no migration. Tests in `test_call_template_autofill.py`
(falsy-vals regression + config onchange fill/preserve).

## v17.0.24.5.0 — No safeguard on the "Move to after booking" (Call Booked) stage; churn removed

Final, clean state for the after-booking destination — it consolidates and
removes the v24.1–v24.4 back-and-forth on this stage (those interim entries are
gone; this is the single source of truth).

**The "Move to after booking" (`call_booked_stage_id`) destination carries NO
validation and NO readiness check.** It is fully auto-managed (auto-created and
paired on first enable by `_sync_call_booked_membership`, same pattern as
`hr_recruitment_test_task`) and must never block saving.

What was removed (vs. the v23.1.0 baseline that shipped the safeguard):
- the two destination `ValidationError`s (dest == Call Stage / dest in another
  job's pipeline) — the constraint is now `_check_call_stage_template`,
  email-template/button checks only;
- `_compute_call_readiness` no longer gates `wont_send` on the destination
  (`blocking_ok` = booking-button AND appointment only);
- the vestigial `call_check_after_stage` field, the `_call_stage_destination_ok()`
  helper, and the `action_open_after_stage` chip action — all existed only to
  power the old safeguard;
- the readiness-alert `<li>` and the hidden `call_check_after_stage` view field,
  and the "After-booking stage" deep-link chip in the "Wired to:" row.

`call_booked_stage_id` stays a plain, editable, auto-populated field on the form
(help: "Auto-populated to the shipped 'Call Booked' stage. Override only for
advanced setups."). No migration (drops are code-only; the column/relation are
untouched).

## v17.0.24.0.0 — Appointment Type is the single source of booking staff; "Booking calendars" field hidden

**Change.** The per-(job, stage) **"Booking calendars (internal staff)"** field
(`recruiter_user_ids`) is **hidden** (config form + create wizard) and its sync
into `appointment.type.staff_user_ids` is **neutralised**
(`_sync_recruiter_staff_users` is now a no-op). Booking staff / calendars are
configured **directly on the Appointment Type** (its `staff_user_ids`), which is
the single source of truth — its slots flow to the Call Stage automatically.

**Why.** The field was a convenience mirror of the type's `staff_user_ids` and a
recurring source of confusion (calendars vs. additional interviewers). The
Appointment Type already drives slot availability natively; one source of truth
is simpler and more supportable.

**Reversible, no migration.** The field + DB column are kept (data left dormant);
`_show_recruiter_avatar_on_booking_type` (auto-enable staff photos) is unchanged.
To roll back: remove `invisible="1"` on the field in both views and restore the
body of `_sync_recruiter_staff_users`.

**Note.** The richer "panel availability" idea (Required/Optional interviewers
with calendar **intersection**) was designed but **shelved** — see the Obsidian
note `hr_recruitment_call_stage - required+optional interviewers (panel
availability)` (ON HOLD). "Additional interviewers" (`interviewer_user_ids`)
stays as-is: attendee-only, does not gate slots.

Tests updated: `test_etap7_recruiter_sync` now asserts the sync is neutralised and
the Appointment Type staff is authoritative; `test_call_stage_settings_ui` seeds
booking staff on the type directly.

## v17.0.23.1.0 — Save-guard no longer rejects ticking a stage with a default template

**Bug.** Ticking *Is Call Stage* on a stage that carries a stage-default
`template_id` (e.g. Odoo's `New` stage → *"Application Acknowledgement"*)
raised `ValidationError: ... has no Book-a-call button` and blocked the
save. Root cause: the `@api.constrains` save-guard
(`_check_call_stage_template_and_destination`) and the readiness helper
resolved the template as `mail_template_id or stage_id.template_id`, which
**diverges from the actual send path** (`hr.applicant._resolve_call_invite_template`
= `mail_template_id` → shipped call-invite, never the stage default). The
guard fired inside `super().write()` — *before* the post-write auto-fill
assigns the per-job call-invite template and the paired Call Booked stage —
so it evaluated the generic stage-default template (no booking button) that
a Call Stage never sends.

**Fix.** `_call_stage_effective_template()` now mirrors the send path: per-job
override first, then the shipped call-invite (`_CALL_INVITE_TEMPLATE_XMLID`),
**not** `stage_id.template_id`. The constraint uses that helper. Net effect:
empty per-job template → guard checks the shipped invite (has the button, and
is exactly what sends) → passes; an *explicitly chosen* button-less per-job
template is still rejected. The send-time guard in `hr.applicant` is unchanged.
Constraint: the stage-default template is **irrelevant** to a Call Stage — it
is never sent. Suite green 167.

## v17.0.23.0.0 — Call Stage Settings dialog: readiness panel, chips, test toolbar, OWL preview

Additive UX redesign of the per-(job, stage) **Call Stage Settings** form
(`view_hr_job_stage_config_form_call`). No booking-lifecycle logic changed.

- **Readiness panel.** Non-stored computes on `hr.job.stage.config`
  (`_compute_call_readiness`): per-check booleans (`call_check_template`,
  `call_check_booking_button`, `call_check_appointment`,
  `call_check_after_stage`, `call_check_staff`) and an overall
  `call_readiness_state` badge (`ready` / `needs_attention` / `wont_send`) in
  the form header. Blocking checks (button / appointment / after-stage) drive
  `wont_send`; staff is a warning. The button-present check reuses
  `booking_button.template_has_booking_token`, so the panel never disagrees
  with the save-time constraint or the send-time guard. The hard save-gate is
  still the `@api.constrains` — the panel only surfaces state. Alert blocks
  (danger/warning/success) list the exact failing items; an inline error sits
  under the template field.
- **Free-slots stat.** `call_free_slot_count_7d` — best-effort count via
  `appointment.type._get_appointment_slots`, in its OWN compute (narrow
  depends) so the heavy slot generation only re-runs on appointment-type
  changes; `-1` = couldn't compute (never blocks). Shown as an
  `oe_stat_button` alongside the applicants count.
- **Test toolbar** (header buttons, Call Stage only): `action_send_test_email`
  (renders against a sample applicant, `[TEST]`-prefixed, to the current
  user — `force_send=True`, so the auto_delete template leaves no `mail.mail`
  behind), `action_open_booking_page` (sample invite `book_url` or
  `/appointment/<id>`), `action_preview_email`.
- **OWL preview modal.** `action_preview_email` renders the effective template
  against a sample applicant and opens a `hr.call.stage.preview` TransientModel
  in a `target='new'` dialog. Its `rendered_body` uses the
  `call_stage_email_preview` OWL field widget
  (`static/src/js/email_iframe_preview.js` + `.../xml/...` + `.../scss/...`,
  shipped in a NEW `web.assets_backend` bundle) which renders the body in an
  isolated `<iframe srcdoc sandbox="">`, with a desktop/mobile width toggle
  (the `device` field) and the resolved `/book/` button outlined. `has_button`
  drives a red "no booking button found" banner. The old
  `display_notification`-based `action_preview_call_invite` is superseded
  (kept on the model for back-compat; the button now calls
  `action_preview_email`).
- **"Wired to" chips.** `action_open_call_template` /
  `action_open_appointment_type` / `action_open_after_stage` /
  `action_open_applicants` — clickable `act_window` deep-links.

ACL: new `hr.call.stage.preview` granted to recruitment user + manager
(`security/ir.model.access.csv`). Tests: `tests/test_call_stage_settings_ui.py`
(readiness states, preview action, chips, toolbar). Note: the appointment
type's `staff_user_ids` is a stored compute that yields empty unless seeded —
tests seed it via the config's `recruiter_user_ids` sync using a real internal
user (the test superuser is filtered by the field's `share=False` domain).

## v17.0.22.0.0 — Button-less invite can never go out (send-time guard + config constraint)

**Problem.** On production, dragging a candidate onto a Call Stage could send
the call-invite email **without** the "Book a call" button. Root cause: the
old logic only injected/validated the booking link inside the
`is_call_stage` branch of `_track_template`. A stage that still had the
call-invite template wired but was **not** (or no longer) marked a Call Stage
— e.g. "Is Call Stage" un-ticked, which deliberately *keeps* the template —
fell through and sent the template with an empty `object.booking_url`, so the
`t-if` hid the button. The candidate got an email with no way to book.

**Fix — two layers, both additive:**

1. **Send-time guard (the permanent fix), `hr.applicant`.** Before any
   call-invite is sent, the resolved template is QWeb-rendered against the
   *actual* applicant and a real booking link is asserted
   (`_call_stage_booking_button_ok` → `booking_button.rendered_has_booking_link`,
   which looks for an `<a href>` on the Appointments `/book/` route, never
   empty / never `#`). Wired into **both** send entrypoints:
   - `_track_template` (tracked drag-to-stage): the non-call-stage branch now
     suppresses + alerts when the template *would* render a booking button
     (`booking_button.template_has_booking_token`); the call-stage branch
     render-verifies right before injecting.
   - `action_send_invite_email` (manual): render-verifies before `send_mail`.
   On failure: **no email**, a `_logger.warning`, and a recruiter follow-up
   activity via `_call_stage_alert_recruiter`. This catches both "template
   missing the button" and "token present but `booking_url` resolved empty".

2. **Config-time constraint, `hr.job.stage.config`
   (`_check_call_stage_template_and_destination`).** When `is_call_stage`,
   blocks save if the assigned template's body has no `object.booking_url`
   (with near-miss hints for `obj.booking_url` / bare `booking_url` / wrong
   case), if its model isn't `hr.applicant`, or if "Move to after booking" is
   self / cross-pipeline. **Only validates template & destination when set** —
   enabling a Call Stage auto-fills the shipped template and pairs the
   destination *after* the initial write, so the constraint must tolerate that
   transient empty state (the post-write writes re-validate the baked values).
   The existing appointment-type constraint is unchanged.

**Shared helper:** `models/booking_button.py` — `template_has_booking_token`,
`detect_near_miss`, `rendered_has_booking_link`. Single source of truth reused
by the guard and the constraint (and, in Phase 2, the readiness panel).

**Tests:** `tests/test_send_time_guard.py` (guard branches incl.
token-present-but-empty-URL; tracked-send suppression of a button-less invite
on a non-call stage; plain emails still pass) and
`tests/test_config_constraint.py` (missing button, near-miss typo, valid
templates save, self / cross-pipeline destination). Three pre-existing tests
that deliberately wired button-less templates were updated to either carry a
valid button body (incidental content) or reproduce the legacy state via raw
SQL (mirroring the existing degenerate-state idiom). Full suite green.

> Phase 2 (UI) — planned, not in this version: readiness panel + status
> chips + test toolbar on the Call Stage Settings dialog, and an OWL
> `<iframe srcdoc>` preview modal (desktop/mobile toggle, highlighted button,
> red banner when the button is absent).

## v17.0.21.0.0 — Attendee additions actually reach Google (need_sync re-arm)

**Bug fixed (follow-up to v17.0.20.0.0).** The candidate (and interviewers)
were correctly added to `event.partner_ids` in the post-create loop, so the
Odoo event form showed them — **but they still got no Google invite.** Root
cause: those attendees are added via a `partner_ids` write that runs *after*
google_calendar's `_google_insert` already ran inside `super().create()` (which
left `need_sync=False`). `partner_ids` is **not** in
`_get_google_synced_fields()` (only `attendee_ids` is), so the write never
re-arms `need_sync` → no `_google_patch` is emitted → Google never learns about
the new guest. The recruiter (an attendee at insert time) got the invite; the
candidate did not. The same latent gap silently affected interviewer add/remove.

**Fix:** both attendee writes now go through
`_call_stage_write_attendees(commands)`, which writes the `partner_ids` commands
and, **when the field exists**, sets `need_sync=True` so Odoo emits an immediate
`_google_patch` (`sendUpdates=all`) and Google emails the new attendee. The
field guard (`'need_sync' in self._fields`) keeps the module installable
**without** the enterprise `google_calendar` module (it is not a hard
dependency — native Odoo invitations still work). Covered by
`tests/test_candidate_attendee.py::test_attendee_change_rearms_google_sync`
(the assertion is scoped to DBs where `google_calendar` is installed). Requires
the event **organiser** to be Google-synced for the push to land (see the
videocall-autolink note).

## v17.0.20.0.0 — Candidate is always an attendee of their booked call

**Bug fixed.** When a **recruiter** booked a call on a candidate's behalf (from
the Call Stage / backend, so `appointment_booker_id` is the recruiter, not the
candidate), the candidate was silently left **off** the event's attendees. The
stock appointment flow seeds attendees from `(staff_user.partner_id | customer)`
where `customer = appointment_booker` (`appointment_type.py:967`); a
recruiter-booker means the candidate's partner is never added. Consequence: no
`calendar.attendee` row, no invitation email, and — critically — the event never
reached the **candidate's Google Calendar** (Google only invites attendees). In
Odoo everything looked fine, which is why it went unnoticed. The public-portal
path was unaffected because there the candidate **is** the booker.

**Fix:** `models/calendar_event.py` →
`_call_stage_ensure_candidate_attendee()`, called in the `create` post-create
loop (next to enrich / auto-advance / add-interviewers). It guarantees
`applicant.partner_id` is on `event.partner_ids` via `(4, id)` (idempotent — a
no-op on the public path). If the applicant has no `partner_id` yet but has an
`email_from`, the email is resolved to a partner via `res.partner.find_or_create`
(attendee-only; we do **not** mutate the applicant's own `partner_id`). The
existing `_call_stage_reconcile_interviewers` already lists
`applicant.partner_id` as `protected`, so once added the candidate is never
dropped by an interviewer delta.

**Scope:** forward-only — existing (already-created) bookings were deliberately
**not** backfilled. Covered by `tests/test_candidate_attendee.py` (recruiter
books → candidate added; email fallback; no double-add on the public path). The
pre-existing `test_interviewers` suite never caught this because its
`_create_event` helper hand-seeds `applicant.partner_id` into `partner_ids`.

## v17.0.19.0.0 — Returning candidate sees their existing booking

A candidate who re-opens the emailed `/book/<code>` link **after** booking now
lands on their booking's confirmation page (Reschedule / Cancel action bar)
instead of the new-slot picker.

**Why.** The `/book/<code>` link redirects (native Appointments) to the
slot-picker page, which has no notion of "already booked" — so a returning
candidate just saw the new-booking UI again and could double-book.

**How.** `CallStageAppointmentController.appointment_type_page` (the route the
`/book` link lands on) is overridden. Via
`_call_stage_existing_booking_redirect(invite_token)` it resolves the applicant
behind the token and searches for an **upcoming, non-cancelled** `calendar.event`
tied to that exact invite (same matching as `_compute_call_status`). If found,
it redirects to `/calendar/view/<event.access_token>?partner_id=<booker>`.

**Reschedule still works.** Reschedule = cancel + rebook; the cancel archives
the event, so the next landing finds no active future event and falls through to
the slot picker. *Schedule another* links omit `invite_token`, so they are
unaffected. Non-recruitment / not-yet-booked links keep the native flow.

## v17.0.18.11.0 — Confirm modals for Cancel / Reschedule

The candidate-facing confirmation page (`appointment.appointment_validated`)
now offers an explicit, themed action bar for recruitment interviews, and the
two destructive actions ask for confirmation before anything happens.

**Why.** Native Odoo renders a single red **Cancel/Reschedule** button whose
`href` points straight at `/calendar/<token>/cancel` — a GET route that cancels
on the first hit. Worse, the invite email/event linked that route *directly*,
so a stray click or an email/link **prefetcher** could silently cancel an
interview with zero confirmation.

**What changed.**

1. **Invite links** (`calendar_event.py::_call_stage_description_context`) — both
   the *Reschedule* and *Cancel* links now point to the confirmation page
   (`/calendar/view/<token>?partner_id=…&cs_action=reschedule|cancel`), never the
   raw cancel route. Landing on the page is a side-effect-free GET, so
   prefetchers can no longer cancel anything. `cs_action` just tells the page
   which confirm modal to auto-open so the link still feels direct.
2. **Confirmation page** (`views/appointment_templates.xml`,
   `appointment_validated_recruitment_actions`) — inherits the stock template.
   For recruitment events **only** (gated on `event.applicant_id`, the native
   related field) it hides the stock button bar and injects:
   - an action bar: *Add to iCal/Outlook* (+ Google) on the left;
     *Schedule another* (ghost) / *Reschedule* (blue outline) /
     *Cancel appointment* (red outline) on the right;
   - a **Cancel** confirm modal ("Cancel this appointment? — cannot be undone")
     and a **Reschedule** confirm modal ("…pick a new time slot"), each with the
     event summary and a prominent safe action (*Keep appointment* / *Go back*)
     beside the destructive confirm.
   The two `position` xpaths are ordered *insert-then-mutate*: the
   `position="after"` (which matches on `hasclass(...)`) must run before the
   `position="attributes"` that rewrites the div's static `class` into a
   `t-attf-class` — otherwise the second match would fail.
3. **JS** (`static/src/js/appointment_validation_confirm.js`) — a `publicWidget`
   on `.o_cs_appointment_actions` (mirrors native `appointment_validation.js`).
   Opens/closes modals (button, backdrop-click, Escape) and auto-opens the modal
   named by `?cs_action=`. The confirm buttons are plain `<a>` so the action
   works even if JS fails.
4. **SCSS** (`static/src/scss/appointment_call_stage.scss`) — all scoped under
   `.o_cs_appointment_actions`; theme CSS variables for neutrals, `$danger` /
   `$warning` for semantics, one brand blue (`#1a73e8`), mobile stacks via
   `media-breakpoint-down(sm)`.

**Odoo reality — reschedule is not a distinct flow.** Odoo implements reschedule
as *cancel-the-old + book-a-new*; there is no route that moves an existing event
to a new slot. So both confirm buttons ultimately hit the same native
`/calendar/<token>/cancel` route; its redirect lands the candidate on the
booking calendar (old slot freed) to pick a new time. The difference the
candidate sees is the modal's intent/wording. The native
`min_cancellation_hours` "too late to cancel" guard still applies (handled by
the native route).

Covered by `test_calendar_event_create`:
`test_customer_description_minimal_layout` (links now go to `/calendar/view`
with `cs_action`, raw `/cancel` link gone) and
`test_validation_page_inherit_injects_confirm_actions` (bar + modals merged into
the combined arch).

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
- ~~`view_hr_recruitment_stage_form_call_inherit`~~ (REMOVED in
  v17.0.24.16.0 — the stage-form call entry was deleted; see that section)
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

**Inherited form contract (HISTORICAL):** `view_hr_recruitment_stage_form_call_inherit`
was **removed in v17.0.24.16.0** together with the stage-form call entry. This
paragraph is retained only to explain older releases; there is no longer any
call-stage inherit on the `hr.recruitment.stage` form.

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

**Confirmation-page actions — added in v17.0.18.11.0** (this superseded the
earlier "deliberately NOT added" decision below). The page is still rendered by
the stock route with no `recruitment_booking` flag, so the new bar gates on
`event.applicant_id` (the native related field, readable on the sudo event)
instead — see the v17.0.18.11.0 section near the top. The links are confirm
modals (no instant cancel), not the duplicated raw `/calendar/<token>/cancel`
buttons referenced below.

_Historical note (pre-v17.0.18.11.0):_ reschedule/cancel/job links on the
confirmation page were considered (the original spec's "step 3c") and dropped at
the time: the `appointment_validated` page carried no `recruitment_booking` flag
(that block would have been dead), `appointment.invite` has no
`cancel_url`/`reschedule_url`, the native page already showed a
"Cancel/Reschedule" button, and `jito_appointment_emails` ships Reschedule +
Cancel buttons (via `/calendar/<token>/cancel`) in the booking emails. NOTE: any
raw `/calendar/<token>/cancel` link still emitted by `jito_appointment_emails`
keeps the one-click-cancel footgun — a candidate follow-up for that module.

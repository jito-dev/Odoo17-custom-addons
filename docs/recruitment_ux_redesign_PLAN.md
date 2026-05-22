# Recruitment UX Redesign — Master Implementation Plan (for AI executor)

> ⚠️ **Superseded for PR sequence and tab order by**
> [`recruitment_master_plan.md`](./recruitment_master_plan.md) (v2, 2026-05-19).
>
> This document (v1) is **still authoritative** for:
> - §1 Constraints
> - §2 Architectural decision (locked-in through-model)
> - §4 UX target / 8-block layout (фінальний tab-order — у v2 §3 PR 6)
> - §6 Cross-cutting non-negotiables
> - §10 Open questions (resolved/triaged in v2 §9)
>
> v2 changes that override v1: split PR 1 → 1a/1b, atomic PR 1b+2 bundle,
> reordered PR 4 ↔ PR 5, expanded `hr.job.stage.config` field set,
> 3 showstopper migration fixes, 12 додаткових тестів.

---

> **Audience:** an AI coding agent (Claude Code / Codex / etc.) that will
> execute this plan end-to-end. Reads as: "given these inputs and these
> constraints, produce these PRs."
>
> **Status:** ready to execute, with the explicit open questions in §10
> resolved by the user before PR 1 starts.
>
> **Companion documents (READ FIRST, do not duplicate their content):**
>
> 1. [`recruitment_vacancy_stages_flow.md`](./recruitment_vacancy_stages_flow.md)
>    — root cause of the "shared stages" bug, full architecture decision
>    for `hr.job.stage.config` through-model, PR 1–5 breakdown,
>    edge-cases table (17 rows), testing strategy. **This is the
>    source of truth for the data model and stages logic.**
> 2. [`recruitment_fields_for_ux_redesign.md`](./recruitment_fields_for_ux_redesign.md)
>    — full catalog of existing + planned fields on `hr.job`,
>    `hr.job.stage.config`, `hr.recruitment.stage`, `hr.applicant`.
>    **This is the source of truth for what fields exist and where they
>    live.** UX grouping proposal (8 blocks) is in §6 of that file.
> 3. [`data_safety_and_migration.md`](./data_safety_and_migration.md)
>    — repository-wide migration safety rules. **Required reading
>    before writing any `migrations/`.**
> 4. [`/home/coder/src/odoo/jito_modules/CLAUDE.md`](../CLAUDE.md)
>    — repo rules: only `jito_modules/` is editable, always reference
>    Odoo 17 source under `odoo17_enterprise/odoo/addons/`, use `tree`
>    not `list`, bump module versions, no demo data, one model per
>    file, write a guide README per module.

---

## 0. Goal in one paragraph

Make creating and configuring a vacancy in this Odoo 17 instance feel
fast, clear and self-explanatory for a recruiter. Concretely:

- Fix the structural bug where stages added under one vacancy leak into
  all others (see companion doc 1, §4).
- Add per-vacancy stage configuration (visibility, email template, test
  task description, booking link, sequence) via a new through-model
  `hr.job.stage.config`.
- Redesign `hr.job` form into the 8-block layout proposed in
  companion doc 2 §6, surfacing existing fields more clearly and
  exposing the new "Stages" tab.
- Do all of the above without breaking existing data, integrations
  (`hr_recruitment_test_task`, `hr_recruitment_forms`,
  `hr_recruitment_extract_openai`, `hr_recruitment_trackers`,
  `hr_recruitment_vacancy_page`, `hr_job_tags`).

Non-goals for this plan: Genio ATS sync, "IQ Test → Cognitive Test"
rename, deeper access-rights work on `scope='global'` (TODO-marked,
not blocking).

---

## 1. Constraints the AI must respect

- **Touch only `jito_modules/`.** Never edit
  `odoo17_enterprise/` or `odoo17_community/`.
- **Odoo 17 APIs only.** When in doubt, grep
  `odoo17_enterprise/odoo/addons/hr_recruitment/` for the actual
  pattern; do not rely on memorized Odoo 16/18 conventions.
- **Views use `<tree>`, not `<list>`.** Project convention.
- **One model per file.** Split if a file grows past ~300 lines.
- **No demo data.**
- **Each module gets a short README** describing what it does,
  main models/views/business logic, and any constraints.
- **Bump `version` in `__manifest__.py`** of every module you edit.
  Increment patch for view-only changes, minor for new fields/models.
- **Do not invent fields or rename existing ones** unless this plan
  says so. The field catalog in companion doc 2 is exhaustive — if
  something is not there, ask before adding.
- **Migrations**: write `migrations/<version>/post-migrate.py`
  scripts per companion doc 3. Never write destructive SQL in pre-
  migrate without a confirmed backup path.
- **Plan → Implement → Hand-in** loop per `jito_modules/CLAUDE.md`.
  Before each PR, post the short plan in chat; after, post a summary.

---

## 2. Architectural decision (locked in)

Adopted from companion doc 1, §0:

```
hr.recruitment.stage   (global catalog; gets new `scope` Selection)
        ▲
        │ stage_id
        │
hr.job.stage.config    (NEW through-model, payload edge of job × stage)
        │
        │ job_id
        ▼
hr.job                 (gets One2many stage_config_ids)
```

`hr.job.stage.config` fields: `job_id`, `stage_id`, `sequence`,
`visible`, `mail_template_id`, `test_task_description`,
`booking_link_id`. `UNIQUE(job_id, stage_id)`. `ondelete=cascade`
on both FKs.

Do NOT replace `hr.recruitment.stage.job_ids` — keep it for backward
compat, but make it the effective consequence of `stage_config_ids`
existing for that job.

---

## 3. Module layout

Create one new module:

```
jito_modules/hr_recruitment_job_stage_config/
├── __manifest__.py
├── __init__.py
├── README.md
├── models/
│   ├── __init__.py
│   ├── hr_recruitment_stage.py    # scope, default_get override
│   ├── hr_job.py                  # stage_config_ids, hidden_stage_count
│   ├── hr_applicant.py            # _read_group_stage_ids, template fallback
│   └── hr_job_stage_config.py     # through-model
├── views/
│   ├── hr_job_views.xml           # new "Stages" tab + 8-block restructure
│   ├── hr_recruitment_stage_views.xml  # scope switcher + banner
│   └── hr_applicant_views.xml     # kanban "N stages hidden" indicator
├── wizard/
│   ├── stage_hide_wizard.py       # confirmation when hiding stage with applicants
│   └── stage_hide_wizard.xml
├── security/
│   └── ir.model.access.csv
└── migrations/
    └── 17.0.1.0.0/
        └── post-migrate.py        # backfill configs from stage.job_ids
```

`depends = ['hr_recruitment', 'mail']`. Add `calendar` only if PR 4
keeps `booking_link_id` here; otherwise split that field into a
sub-module `hr_recruitment_call_stage` (preferred, see §5 PR 4).

---

## 4. UX target (what the form should look like)

Companion doc 2 §6 lists the 8 blocks. The AI must render `hr.job`
form as:

```
┌─ Header: name, status (recruit/open), recruiter (avatar), color, ★fav ─┐

[ Smart buttons: Applicants | CVs | Trackers | Hires ]

╔ Tab: Identity ════════════════════════════════════╗
  Department · Company · Location · Contract type
  Hiring manager · HR responsible · Interviewers · Tags

╔ Tab: Headcount & timing ═════════════════════════╗
  no_of_recruitment · expected_employees · date_from/to

╔ Tab: Description ════════════════════════════════╗
  description (Html, full width)
  ─ AI panel (collapsible) ─
    job_description_attachment_ids → [Extract with AI]
    requirement_statement_ids (tree, AI-extracted)
    weights (experience/project/company/credibility)

╔ Tab: Public page ════════════════════════════════╗
  website_published toggle
  use_published_config toggle
   └─ if on: published_title, published_short_desc,
            published_long_desc, published_salary_display,
            published_experience_display
  process_steps, process_time_to_answer, process_days_to_offer

╔ Tab: Application form ═══════════════════════════╗
  use_forms · form_template_id
  form_show_phone/linkedin/resume/intro
  question_line_ids (tree with "inherited from template" badges)

╔ Tab: Stages 🆕 ══════════════════════════════════╗
  stage_config_ids (editable tree, drag-handle)
   Columns: Seq | Stage | Visible | Email | TestTask | Booking
   Hidden stages section (collapsed by default)

╔ Tab: AI & bulk ══════════════════════════════════╗
  ai_match_mode · run_ai_match_on_bulk · run_ai_experience_on_bulk
  cv_attachment_ids drop-zone, bulk progress panel

╔ Tab: Tracking & sources ═════════════════════════╗
  tracker_ids (smart-button + inline tree)
```

The applicant kanban inside a job gets a passive banner
`🔒 N stages hidden in this job · Manage` (only when N > 0)
that opens the Stages tab scrolled to the Hidden section.

---

## 5. PR sequence (each PR = one merged unit of work)

### PR 1 — Foundation: per-job stage configuration

**Files:**

- New module `hr_recruitment_job_stage_config/` (skeleton from §3).
- `models/hr_job_stage_config.py`: define model + unique constraint
  + cascade.
- `models/hr_recruitment_stage.py`: add `scope` Selection
  (compute+store, writable). Override `default_get`: when
  `default_job_id` in context, set `scope='specific'` and
  `job_ids=[(6,0,[default_job_id])]`. **Do not pop `default_job_id`**
  (this is the bug fix from companion doc 1 §4).
- `models/hr_job.py`: `stage_config_ids = One2many(...)`.
- `models/hr_applicant.py`: override `_read_group_stage_ids` per
  companion doc 1 §3.2 (filter by config.visible, fallback to
  globals minus hidden ones).
- `views/hr_recruitment_stage_views.xml`: scope switcher (radio),
  conditional `job_ids` M2M (visible only when scope=specific).
- `views/hr_job_views.xml`: new "Stages" tab with editable tree of
  `stage_config_ids` (columns: sequence, stage_id, visible,
  mail_template_id). Drag-handle on sequence.
- `migrations/17.0.1.0.0/post-migrate.py`: for every existing
  `hr.recruitment.stage` with non-empty `job_ids`, create
  `hr.job.stage.config(job_id, stage_id, visible=True,
  mail_template_id=stage.template_id)` rows. Stages with empty
  `job_ids` keep `scope='global'`; no config rows created until
  user opts in.
- `security/ir.model.access.csv`: full CRUD for
  `hr.group_hr_user` on `hr.job.stage.config`.
- Tests under `tests/`:
  - `test_stage_scope.py`: creating stage from job kanban results in
    `scope='specific'` + `job_ids=[job]`; from Configuration it
    results in `scope='global'`.
  - `test_kanban_filtering.py`: applicant kanban for Job A does not
    show stages specific to Job B; globals appear in both.
  - `test_migration.py`: snapshot fixture with stages having
    `job_ids` → after migration, matching config rows exist with
    `visible=True`.

**Acceptance criteria for PR 1:**

- Existing recruiters open any vacancy and see all stages they used
  to see (no regressions).
- Creating a new stage via "+ Stage" inside a job kanban now creates
  a job-specific stage (scope='specific', visible only in that job).
- New "Stages" tab on `hr.job` form is present, editable, persistent.
- All existing tests in dependent modules still pass.

### PR 2 — Email templates per job

**Goal:** make `mail_template_id` on `hr.job.stage.config` actually
drive the email sent when an applicant moves into that stage in that
job, falling back to `stage.template_id` otherwise.

**Files:**

- `models/hr_applicant.py`: override `_track_template` to look up the
  config row first (companion doc 1 §3.2 fallback chain). Keep
  unchanged behaviour when no config row exists.
- Tests:
  - `test_template_fallback.py`: applicant moved to stage S in job J
    with config.mail_template_id set → that template is used. Same
    move in job K without override → `stage.template_id` is used.

**Refactor target:** `hr_recruitment_test_task` currently writes to
`stage.template_id` globally (search for `CRITICAL FIX` comments
in that module). Migrate that writer to `hr.job.stage.config` for
the relevant job and remove the global mutation.

### PR 3 — Hide stages per job

**Goal:** `visible` toggle in the Stages tab actually hides the stage
column from that job's applicant kanban; hidden stages remain
discoverable per companion doc 1 §2.5 (four entry points: form tab
Hidden section, kanban toolbar banner, global Stages config column,
applicant search filter).

**Files:**

- `wizard/stage_hide_wizard.py`: when toggling `visible=False` on a
  config row whose stage currently has applicants in that job, open
  the wizard. Three actions: (a) move applicants to another visible
  stage (dropdown), (b) hide anyway (applicants kept on hidden
  stage), (c) cancel.
- `views/hr_job_views.xml`: Hidden stages collapsible group below
  the main Stages tree. Visual cue: muted row, eye-slash icon,
  "Hidden" badge.
- `models/hr_job.py`: `hidden_stage_count` (compute).
- `views/hr_applicant_views.xml`: kanban toolbar banner
  `🔒 {{hidden_stage_count}} stages hidden in this job · Manage`,
  rendered only when count > 0. Manage link opens job form on
  Stages tab.
- Applicant search panel: filter "Include hidden stages".
- Tests:
  - `test_hide_stage.py`: hiding a stage removes it from
    `_read_group_stage_ids`; "include hidden" filter brings it back.
  - `test_hide_with_applicants.py`: wizard appears, "move" action
    relocates applicants atomically, "hide anyway" preserves them.

### PR 4 — Call stage / booking link (separate sub-module)

**Goal:** introduce a "call" stage type with a bookable link a
candidate can use to self-schedule.

**Files:**

- New sub-module `jito_modules/hr_recruitment_call_stage/` depending
  on `hr_recruitment_job_stage_config` and `calendar` (or
  `appointment` if available — check `odoo17_enterprise/odoo/addons/`
  before deciding).
- `models/hr_job_stage_config.py` (extend): add
  `booking_link_id = M2O('calendar.appointment.type')`.
- `views/`: add "Booking" column to the Stages tree.
- Email template helper: expose `{{ stage_config.booking_link_id.url }}`
  in the mail.template rendering context for applicant moves.
- Tests: `test_call_stage.py`.

**Open question (§10.3):** confirm `calendar.appointment.type` is the
right backing model before writing the FK. If user wants Calendly /
generic URL, switch to `Char` and document.

### PR 5 — Test task description per job

**Goal:** stop relying on a single global "Test Task" stage description;
let recruiters write the test task content per job.

**Files:**

- `hr_recruitment_test_task/models/hr_applicant.py`: when generating
  the test-task email/page, read from
  `hr.job.stage.config.test_task_description` for the applicant's job
  and stage. Fallback to current behaviour if empty.
- `views/hr_job_views.xml` (in `hr_recruitment_job_stage_config`):
  expose `test_task_description` as an expandable HTML editor under
  each stage row (accordion or side-panel — design decision).
- Bump `hr_recruitment_test_task` version; deprecate any global
  description field if one exists.
- Tests: `test_test_task_per_job.py`.

### PR 6 — `hr.job` form restructure (UX redesign proper)

**Goal:** the visual reorganization described in §4. This PR is
**view-only** plus minor CSS, no model changes.

**Files:**

- Extend `hr.job` form view inside
  `hr_recruitment_job_stage_config` (or a thin new module
  `hr_recruitment_job_form_redesign/` if preferred for separation).
- Reorganize existing fields into the 8 tabs per §4.
- Inherit and reposition fields from sibling modules
  (`hr_recruitment_vacancy_page`, `hr_recruitment_extract_openai`,
  `hr_recruitment_forms`, `hr_recruitment_trackers`,
  `hr_job_tags`, `hr_recruitment_test_task`) using
  `position="move"` / `position="replace"` carefully so each
  module's own form-extension still loads.
- Add CSS only as needed for the AI panel, drop-zone, drag-handle.
  Keep it in a single `static/src/scss/job_form.scss`.

**Acceptance criteria for PR 6:**

- All fields enumerated in companion doc 2 are reachable from the
  new form. Nothing is hidden by accident.
- Module load order tested: enabling/disabling any one sibling
  module does not blow up the form (use `<xpath>` with safe
  selectors, not positional indices).

---

## 6. Cross-cutting non-negotiables

- **Backward compat.** Every PR must leave older databases bootable
  without manual intervention. Migration scripts must be idempotent
  (re-runnable).
- **Performance.** `_read_group_stage_ids` is hit on every kanban
  load. The override must not do N+1 queries — single read of
  `hr.job.stage.config` filtered by job_id, then set arithmetic.
- **Multi-company.** `hr.job` is company-bound; `hr.recruitment.stage`
  is not. Do not add `company_id` to `hr.job.stage.config` unless
  tests show a leak — defer until a real multi-company bug surfaces.
- **Logging.** Stage scope changes and `visible` toggles should
  post a chatter message on the stage (and on the job for visibility
  changes). Use `message_post` from `mail.thread`.
- **No silent renames.** If you have to rename an existing field
  to fit the new design, write the migration and update every
  inheriting view across `jito_modules/`. Otherwise, leave the
  field name and only change `string="..."`.

---

## 7. Edge cases checklist (excerpt — full list in companion doc 1 §4)

Before merging each PR, walk through the relevant rows of the
17-row edge-case table in companion doc 1 §4. The most load-bearing
ones for this plan:

- Row 1: hiding a stage that has applicants → wizard.
- Row 10: cloning a job copies `stage_config_ids`.
- Row 12: refactor `hr_recruitment_test_task` to write to config,
  not to `stage.template_id`. Remove "CRITICAL FIX" hack.
- Row 13: data migration script for existing stages with `job_ids`.
- Row 16: applicant changing `job_id` resets `stage_id` to the new
  job's default visible stage.

---

## 8. Testing strategy (binding)

For each PR the AI must produce:

1. **Unit tests** for every new method on every new model.
2. **Integration test** that boots a fresh Odoo with the module
   chain installed and exercises the user-facing flow end-to-end
   (create job → add stage → move applicant → email sent).
3. **Migration test** if the PR ships a migration script: load
   a fixture DB that simulates pre-migration state, run the script,
   assert post-state.
4. **Manual QA script** in markdown under the module's
   `scripts/qa_*.md` — minimum 10 scenarios, including the
   companion-doc-1 §2.5 "find hidden stages" four-entry-point check.

CI command (run locally before declaring done):

```
odoo-bin -c <conf> -i hr_recruitment_job_stage_config \
  --test-enable --stop-after-init \
  --log-level=test
```

Repeat with `-u` (update) on a snapshot of production-like data.

---

## 9. Hand-in checklist (per PR)

The AI must finish each PR with a markdown summary containing:

- What changed (modules, files, models, views).
- Migration scripts shipped + how to run them on a snapshot.
- Tests added and how to run them.
- Screenshots/recordings of the user-facing change (at minimum:
  before/after of the affected form/kanban view).
- Open follow-ups punted to a later PR.

Per `jito_modules/CLAUDE.md` SDLC §3.

---

## 10. Open questions to resolve BEFORE PR 1 starts

These come from companion doc 1 §7. The AI must NOT proceed past
PR 1 without explicit user answers to (1) and (3).

1. **Access rights on `scope='global'`** — restrict toggling
   "global" to `hr.group_hr_manager`, or leave open to all
   recruiters? (Default if unanswered: leave open, add TODO.)
2. **Per-job stage rename** (`display_name` on
   `hr.job.stage.config`) — needed? (Default: skip for PR 1.)
3. **Booking link backing model** — `calendar.appointment.type`
   (Odoo Appointment app) or a free-form Char URL (Calendly etc.)?
   This decides PR 4's dependencies.
4. **Genio ATS sync** — does it need external_id mapping on
   `hr.job.stage.config`? (Default: punt to a later PR.)
5. **"IQ Test → Cognitive Test" rename** — bundle with PR 1 to
   avoid name collisions, or separate PR? (Default: separate PR.)

---

## 11. Where to start, exactly

1. Read companion docs 1, 2, 3 and `jito_modules/CLAUDE.md`.
2. Grep `odoo17_enterprise/odoo/addons/hr_recruitment/` for
   `default_get`, `_read_group_stage_ids`, `_track_template` to
   confirm the patterns this plan refers to are present in the
   actual installed code.
3. Ask the user the questions in §10.1 and §10.3.
4. Scaffold `hr_recruitment_job_stage_config/` per §3.
5. Implement PR 1 (§5) end-to-end including tests and migration.
6. Hand in per §9. Stop. Wait for user sign-off before PR 2.

That's it. Everything else is in the companion docs.

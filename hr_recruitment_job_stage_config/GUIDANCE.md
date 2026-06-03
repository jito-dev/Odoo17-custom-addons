# Guidance — hr_recruitment_job_stage_config

## What this module is for

This is the **stages-first foundation** of the recruitment redesign
(master plan §3 PR 1b). Every later module — hidden stages (PR 3),
test-task description per job (PR 4), call stage / booking link (PR 5),
and the form restructure (PR 6) — extends `hr.job.stage.config` instead
of touching the global `hr.recruitment.stage` directly.

Treat the master plan (`jito_modules/docs/recruitment_master_plan.md`)
as the spec of record. This file is a developer-side companion.

## Architectural invariants — do not break

1. **`hr.applicant.stage_id` is never mutated by this module.** Not by
   the migration, not by overrides, not by inverses. The R2 safety
   verification logs proof of this on every install/upgrade.
2. **`config.mail_template_id` is the source of truth** for per-job
   email overrides; `stage.template_id` is the fallback for new
   `(job, stage)` pairs only. Modules that need a custom invite template
   must write to `hr.job.stage.config.mail_template_id`, NOT to
   `stage.template_id`.
3. **`_read_group_stage_ids` must keep `access_rights_uid=SUPERUSER_ID`
   and the `order` argument intact**; otherwise interviewer roles lose
   columns and the kanban order desynchronises from job_view sequence.
4. **`_compute_stage` must skip hidden stages.** The override exists
   solely to prevent R10: stock Odoo doesn't know about
   `config.visible=False` and can land a new applicant on a hidden
   stage, which then disappears from the kanban.
5. **`_track_template` returns a recordset, not a callable.** Odoo 17's
   tracking API does not accept lazy/closure templates.
6. **`config.mail_template_id` must point at a template whose model is
   `hr.applicant`.** Enforced by `@api.constrains` and a runtime guard
   in `_track_template`. Without this, `mail.template` rendering crashes
   at `self.env[self.model]` with `KeyError: False`. The popup form uses
   `no_create` / `no_create_edit` on the picker so recruiters cannot
   create misconfigured templates from this UI; new templates go through
   Settings → Technical → Email Templates with admin access.

## Where to add new payload

Adding a per-job field for a future PR? Two cases:

- **Stable per-job state** (e.g. per-job hired_stage flag, per-job
  weight) — add a column to `hr.job.stage.config` and update the
  `_PAYLOAD_FIELDS` tuple in `hr_job_stage_config.py` so the auto-row
  cleanup (in stage scope flip) recognises the new field as payload.
- **List-shaped per-job state** (e.g. links, questions per stage) — add
  a child model that has `config_id` as M2O ondelete=cascade, like
  `hr.job.stage.config.link`. Update `_has_payload()` to count the
  child as "payload" when non-empty.

## Migration policy

Backfill logic lives in `hooks.py` (`run_backfill`). Both the install
path (`post_init_hook`) and upgrade path
(`migrations/17.0.1.0.0/post-migrate.py`) call the same function. It is
idempotent — re-running creates zero rows. Always extend that single
function rather than forking the logic.

The pre-snapshot/diff guard is fast (single SELECT) and is worth keeping
even on tiny databases — it is the only programmatic proof of the R2
guarantee.

## v17.0.1.0.14 — `_inverse_scope` keeps config rows when flipping to global

**Symptom before the fix:** a global stage could appear in a job's kanban
but be missing from that job's Stages tab. Two paths produced the state:

1. Recruiter creates a stage as `scope='specific'` for one job, then opens
   the stage form and flips `scope` to `global`. The old `_inverse_scope`
   unlinked all auto-rows (config rows without payload), leaving the
   stage with no `hr.job.stage.config` row on any job.
2. SQL-level inserts / restored backups / interrupted earlier migrations
   that bypassed the `create()` override.

In both cases:
- Kanban (per-job) showed the stage, because `_visible_stages_domain`
  treats a global stage as visible unless explicitly hidden via a config
  row with `visible=False`. No row at all = not hidden = visible.
- Stages tab (per-job) did not show the stage, because the tab is
  built from `stage_config_ids` (a One2many of `hr.job.stage.config`).

**Fix architecture:**

`_inverse_scope` for `scope='global'` no longer unlinks auto-rows. It
preserves every existing row AND creates a row for every job that does
not yet have one, using `visible=stage.default_visible_in_new_jobs`
(same default as `hr.job.create` for new jobs). Then it clears
`job_ids` (the scope is global — no specific jobs).

**Invariant after v17.0.1.0.14:** for every applicable `(job, stage)`
pair, exactly one `hr.job.stage.config` row exists. The Stages tab is
therefore a faithful mirror of what the kanban can show.

**Migration:** `migrations/17.0.1.0.14/post-migrate.py` backfills
orphan `(job, global_stage)` config rows on upgrade. Visible defaults
to `stage.default_visible_in_new_jobs`. Idempotent
(`ON CONFLICT (job_id, stage_id) DO NOTHING`); never mutates existing
rows; never touches `hr.applicant.stage_id` (R2 guarantee).

**Override-row safety:** rows with payload (mail template, links,
fold, etc.) are unaffected — both before and after this fix they
survive the flip. The behavioural change is only that **auto-rows now
survive too**, instead of being deleted.

**Why not keep deleting auto-rows:** the previous design assumed
"global = no rows = visible everywhere by default". That made the
Stages tab and the kanban inconsistent (kanban knows globals exist;
Stages tab needs a row to display anything). The single-row-per-pair
invariant is the simplest model and matches what `_sync_stage_configs`
("Sync stages" button) already enforces on demand.

## v17.0.1.0.13 — `_PAYLOAD_FIELDS` reserves call-stage names

**What:** the `_PAYLOAD_FIELDS` tuple in `models/hr_job_stage_config.py`
gained three new names — `is_call_stage`,
`booking_appointment_type_id`, `call_booked_stage_id`. These columns are
declared by the **sub-module** `hr_recruitment_call_stage` (PR 5), not
by this foundation; the tuple reserves the names ahead of time so that
`_has_payload()` recognises them as payload as soon as the sub-module
is installed.

**Why this lives in the foundation, not in the sub-module:** without
this, a recruiter flipping a call-stage's `scope` from `specific` to
`global` would trigger `_inverse_scope` (line 69), which calls
`_has_payload()` on each config row to decide which auto-rows are safe
to unlink. If the new names were unknown to the tuple, a row whose only
state is `is_call_stage=True` plus an appointment type would be
classified as "auto" and **silently deleted**.

**Foundation-only safety:** `_has_payload()` now skips names absent from
`self._fields` so an install without the sub-module does not crash on
scope-flip.

**Contract for future sub-modules:** when adding per-(job, stage)
payload, you MUST either (a) extend this tuple in a foundation commit
shipped in the same release bundle as your sub-module, or (b) ensure
your sub-module is installed before any recruiter can flip
`scope='specific' → 'global'` on a row carrying your payload. Option
(a) is the pattern in use; option (b) is fragile and discouraged.

**Migration:** none. Tuple extension only changes runtime cleanup
decisions for future scope flips; no schema change, no row mutation.

## v17.0.1.0.12 — per-job sequence and fold in the applicant-form statusbar

**Symptom before the fix:** after v17.0.1.0.11 the dropdown and the
statusbar correctly hide invisible stages, but the **order** and
**fold** in the statusbar remained global:

- Statusbar sorts stages by `hr.recruitment.stage._order = 'sequence'`
  — that is the global `stage.sequence`, not
  `hr.job.stage.config.sequence`.
- `fold_field='fold'` reads `hr.recruitment.stage.fold` — a global
  flag that ignores `hr.job.stage.config.fold`.

In other words, a recruiter can reorder stages per-job in the Stages
tab of the job — but the statusbar on the applicant form still shows
them in the global order.

**Fix architecture — context-driven, no OWL patch:**

1. A new context key `applicant_stage_job_id` signals "use the per-job
   config for this job". The applicant-form view sets it on the
   `stage_id` field:
   ```xml
   <field name="stage_id" widget="statusbar"
          context="{'applicant_stage_job_id': job_id}"
          options="{'clickable': '1', 'fold_field': 'display_fold'}"/>
   ```
2. `hr.recruitment.stage._order_to_sql` override: when the context
   carries `applicant_stage_job_id` and the caller relies on the
   default `_order`, the query gets a
   `LEFT JOIN hr_job_stage_config ON (stage_id = stage.id
   AND job_id = $ctx_job_id)` plus
   `ORDER BY config.sequence NULLS LAST, <stock order>`. Stages with a
   config row for this job are ordered by `config.sequence`; stages
   without one (legacy globals without backfill) fall into tail-order
   via `stage.sequence`.
3. Computed Boolean `hr.recruitment.stage.display_fold` with
   `@api.depends_context('applicant_stage_job_id')`: under the
   context it returns `config.fold` for `(stage, ctx_job_id)`; without
   the context, or without a config row, it returns `stage.fold`.

**Opt-out:** explicit `order=...` in `_search` (reports, exports,
custom queries) is left alone — the context override only fires when
`order == self._order` (or `order=None`, which means the same thing).

**R2 / R10 unaffected:**
- No `hr.applicant.*` field is changed; no `applicant.stage_id` is
  mutated.
- Visibility keeps working through `allowed_stage_ids` (v17.0.1.0.11).
  This PR only adds **order** and **fold** as orthogonal dimensions.
  R10 ("the current stage is always in the allowed set") still holds.

**Why not an OWL patch on `StatusBarField`:** an OWL patch is 5× the
code, forces a dependency on the internal web-module API, and breaks
on every Odoo upgrade. Server-side `_order_to_sql` plus a computed
field is the minimum amount of code and is consistent with how
`allowed_stage_ids` already works.

**Why not duplicate sequence handling in `_compute_stage`:**
`_compute_stage` uses `config.sequence` to pick the **default** stage
for a new applicant — that is a separate concern (picking one stage,
not sorting a list), and it does not need the SQL JOIN there.

**Migration:** not required. Changes are fully additive — a new
computed field (no DB column), a new view, and an SQL hook override
(Python only).

## v17.0.1.0.11 — `allowed_stage_ids` makes the form dropdown respect per-job visibility

**Symptom before the fix:** kanban columns correctly hid stages with
`hr.job.stage.config.visible=False` (via `_read_group_stage_ids`), but
the **dropdown / statusbar / tree inline-edit / kanban quick-create /
search autocomplete** still surfaced hidden stages. Cause: the stock
`hr.applicant.stage_id` field has a static domain
`['|', ('job_ids', '=', False), ('job_ids', '=', job_id)]`
(`odoo17_enterprise/.../hr_applicant.py:44-48`) that knows nothing
about `config.visible`.

**Fix architecture — single source of truth:**

1. A shared helper
   `HrApplicant._visible_stages_domain(job_id, current_stage_ids)`
   returns a search domain on `hr.recruitment.stage` using a single
   rule:
   ```
   (scope='global'   AND id NOT IN hidden_for_job)
   OR (scope='specific' AND id IN     visible_specific_for_job)
   OR (id IN current_stage_ids)        -- R10 safety
   ```
2. `_read_group_stage_ids` now delegates to this helper (kanban
   behaviour is preserved; the refactor extracts the OR formula into a
   shared function).
3. `allowed_stage_ids` — a non-stored computed M2M on `hr.applicant`
   that calls the same helper; `@api.depends('job_id', 'stage_id')`.
4. The `stage_id` field is re-declared with
   `domain="[('id', 'in', allowed_stage_ids)]"` — every other
   attribute (`compute='_compute_stage'`, `store=True`,
   `readonly=False`, `tracking=True`, `group_expand`,
   `ondelete='restrict'`, `copy=False`, `index=True`) is preserved
   unchanged.
5. The inverse
   `stage_config_ids = One2many('hr.job.stage.config', 'stage_id')`
   is added on `hr.recruitment.stage` for transparent ORM access.

**R10 invariant:** the applicant's current `stage_id` is **always** in
`allowed_stage_ids`, even if the config flipped to hidden after the
applicant landed there. The applicant therefore stays editable (other
fields, chatter, buttons) — the recruiter is not stuck.

**Migration:** `migrations/17.0.1.0.11/pre-migrate.py` backfills
orphan `hr_job_stage_config` rows for `(job, stage)` pairs that exist
in `hr_recruitment_stage_hr_job_rel` but have no config row. Without
this, specific stages without a config (legacy or partially-backfilled
data) would disappear from the dropdown. The script is idempotent,
additive-only, and does not touch `hr_applicant.stage_id` (R2).
Details in
[`docs/migration_17_0_1_0_11_instruction.md`](../docs/migration_17_0_1_0_11_instruction.md).

**What is NOT covered in Phase 1 (deferred in
[`docs/later.md`](../docs/later.md) #6):**

Server-side write paths that set `stage_id` directly and bypass the
domain (domains apply only to UI widgets):

- stock `hr.applicant.reset_applicant()`;
- `jito_modules/hr_recruitment_test_task/controllers/main.py:51`
  (portal submission of a test task);
- `jito_modules/iq_tests_survey/models/iq_user_input.py:82`
  (IQ test completion).

Phase 2 will add guards in these paths. For now the UI is correct,
but if a recruiter hides, say, "Test Task Submitted" for job B, an
external controller can still drop a candidate there (this is not a
regression — it is the current state until Phase 2).

**Why not name_search / view inherit / dotted-path domain:** a dotted
path (`stage_config_ids.visible`) is not reliable for `name_search`;
a `name_search` override does not cover the statusbar; per-view XML
inheritance requires 7+ touch points and breaks on every Odoo
upgrade. A field-level domain plus a computed M2M is the minimum code
for the maximum coverage.

## v17.0.1.0.6 — drop `default='global'` on `scope` (kanban "+ Stage" actually works now)

**Symptom (re-investigation):** after v17.0.1.0.5 with
`precompute=True` the user still gets **`scope='global'` AND empty
`job_ids`** when creating a stage via kanban "+ Stage". The tests
`test_default_get_with_job_context_makes_stage_specific` and
`test_scope_persisted_as_specific_on_kanban_create` fail on
`assertIn(self.job_a, stage.job_ids)` — the M2M is empty right after
`create()`.

**The actual root cause** (the v17.0.1.0.5 GUIDANCE was wrong about
the reason):

Sequence inside `super().create(vals_list)`:
1. Our `create` override inserts `vals['job_ids'] = [(6, 0, [job_id])]`.
2. `_prepare_create_values` → `_add_missing_default_values` calls
   `default_get(missing_defaults)`. The `scope` field has
   `default='global'`, so `default_get` returns `'global'` and
   `vals['scope'] = 'global'`.
3. `_add_precomputed_values` SKIPS `scope` because `'scope' in vals`
   (precompute only fires for missing keys).
4. `scope` is NOT added to the `precomputed` set, so the main `create`
   loop (`models.py:4597`) does `inversed['scope'] = 'global'`.
5. SQL INSERT with `scope='global'` and `job_ids=[X]` in the relation
   table.
6. `_inverse_scope` runs with `scope='global'` →
   `stage.job_ids = [(5, 0, 0)]` → **deletes the M2M row that was just
   created**.
7. Consequence: the post-super loop sees `stage.job_ids` empty →
   falls into the `else` branch for global stages → creates one
   `hr.job.stage.config` per job with
   `visible=stage.default_visible_in_new_jobs` (usually False) instead
   of a single row for the current job with `visible=True`.

**Fix:** drop `default='global'` from the `scope` field. Now
`_add_missing_default_values` does not add `scope` to vals →
`_add_precomputed_values` computes `scope` from
`self.new(vals).job_ids` → the `precomputed` set contains `scope` →
`_inverse_scope` does NOT run after INSERT. The form-driven scope
switcher is unchanged — `write({'scope':...})` still calls the
inverse explicitly.

**Invariant:** after
`Stage.with_context(default_job_id=X).create({'name':...})`
- `stage.job_ids == hr.job(X)`;
- `stage.scope == 'specific'` (in both DB and cache);
- there is **exactly one** `hr.job.stage.config` row `(X, stage)`
  with `visible=True`.

**Inverse on a manual flip** (`stage.scope = 'global'`) keeps working
as before: the field is in vals explicitly → the inverse runs →
clears `job_ids`.

**Compatibility:** the 17.0.1.0.6 migration re-syncs `scope` for
existing rows via the same `_recompute_scope` helper we already use
in `post_init_hook`. No destructive operations.

## v17.0.1.0.5 — `precompute=True` on `scope` (PARTIAL — see 17.0.1.0.6)

> **STATUS:** insufficient. `precompute=True` alone did not fix the
> problem, because `default='global'` still ended up in `vals` via
> `_add_missing_default_values`, and precompute only fires for MISSING
> keys. The full fix is in 17.0.1.0.6 (drop the default). The entry
> below is kept for historical transparency; do not rely on it as a
> full root-cause description.

**Symptom:** clicking "+ Stage" in the kanban of applicants for a
specific job — opening the stage form via the gear shows
`Scope: Global` instead of `Specific`.

**Wrong hypothesis:** Odoo 17 (`models.py:4632`) guards editable
computed-stored fields from being recomputed inside `create()` — and
`scope` has an `inverse=`, so it counts as editable. (The correct
part: the guard exists. The wrong part: the regression is not caused
by the guard; it is caused by `_inverse_scope` running AFTER INSERT
and clearing `job_ids` — see 17.0.1.0.6.)

## v17.0.1.0.2 — Auto-create config rows on stage.job_ids writes

> **Status:** IMPLEMENTED. Realised by the `hr.recruitment.stage.write`
> override (`models/hr_recruitment_stage.py:127`), which captures
> `job_ids` before super, then calls `_ensure_config_rows_for_jobs` for
> any newly-added job. `_inverse_scope` covers the explicit-scope path;
> the `write` override covers the direct `job_ids` path used by
> downstream modules (`hr_recruitment_test_task`, `iq_tests_survey`).
> See [`docs/recruitment_test_task_iq_stages_fix_plan.md`](../docs/recruitment_test_task_iq_stages_fix_plan.md)
> for the original plan document.

**Foundation-module invariant:**

Any write to `hr.recruitment.stage.job_ids` — via `write()`,
`create()`, or the ORM commands `(4, id)` / `(6, 0, ids)` /
`(3, id)` / `(5, 0, 0)` — must **guarantee** the presence of an
`hr.job.stage.config` row `(job_id, stage_id, visible=True)` for every
newly-added job. This extends the current (and future)
`_inverse_scope` logic to external writes on `job_ids`, which used to
skip the config-create step and ended up with stages invisible in the
kanban.

**Contract for downstream modules:**

- Writing `stage.write({'job_ids': [(4, job.id)]})` directly is fine;
  the foundation will create the config row with `visible=True`.
- Do not (and need not) duplicate `hr.job.stage.config.create` in
  your own module — this is the single source of truth.
- A manual `config.visible=False` is never overwritten: the
  idempotent create skips existing rows.
- When a job is removed from `job_ids`, the config row is **NOT
  deleted** — an applicant may live there (R10 safety).

## v17.0.1.0.1 — Stages-tab UX overhaul

- The job-form Stages tab is **non-editable**: all applicable stage rows
  are auto-populated when the job is created (`hr.job.create`) and when
  a new global stage is created (`hr.recruitment.stage.create`). The
  recruiter only toggles `visible` or opens a row for detail editing.
- Default visibility on new rows follows
  `stage.default_visible_in_new_jobs`. Whitelist is **New, Initial
  Qualification, First Interview, Second Interview, Contract
  Proposal**; everything else defaults to hidden. The post-migrate
  seeds this flag and backfills missing rows (force-visible if an
  applicant is already there).
- `config.action_toggle_visible` is the entry point for the per-row
  hide/show button. Empty rows flip silently; rows with applicants
  return the `hr.job.stage.config.hide.confirm` wizard. **Applicants
  are never deleted** — only `config.visible` flips.
- `hr.job.stage.create.wizard` is the only path to create a new
  job-specific stage from the job form. It copies payload from a
  selected source's **config row** (not `stage.template_id`) so the
  per-job email override carries over correctly.

## Compatibility with the standalone PR 1a module

`hr_recruitment_stage_default_fix` is the half-day BUG-fix that shipped
ahead of this PR. Its `default_get` override is a strict subset of ours
— both modules can coexist because the supers chain idempotently.

If you ship this module on a database that already runs the standalone
fix, leave the standalone module installed; uninstalling it later is
safe but not required.

## Cross-module audits to keep in mind

When adding logic that touches stages or templates, grep across
`jito_modules/` for:

- `stage.template_id =` / `'template_id':` writes — should now write to
  `hr.job.stage.config.mail_template_id`. The legacy hack in
  `hr_recruitment_test_task` (the famous `# CRITICAL FIX`) is removed in
  PR 2 (v17.0.1.0.4); do not bring it back.
- `_read_group_stage_ids` overrides — must remain compatible with the
  config-driven domain in this module. Don't drop
  `access_rights_uid=SUPERUSER_ID`.
- `base.automation` / server actions filtering by `stage_id` — these are
  unaffected by hiding, but if they create applicants with a stage_id
  they should also respect `config.visible` (use the same compute logic
  as `_compute_stage`).

## When to ship

PR 1b and PR 2 (`hr_recruitment_test_task` refactor) are an **atomic
release bundle**. Do not deploy PR 1b alone — `_manage_test_task_stages`
will keep writing `stage.template_id` until PR 2 lands, and per-job
overrides set after PR 1b install will be silently overwritten on the
next job write.

Acceptance criteria from master plan §3:

- Existing jobs open — kanban looks identical (R2 / additive
  guarantee).
- `+ Stage` from a job kanban creates `scope='specific'` with the job
  in `job_ids` and a config row already present.
- The new Stages tab on the job form lists every config row with a
  drag handle, Visible toggle, and the resolved effective template.
- The `_manage_test_task_stages` flow no longer writes
  `stage.template_id`; two jobs with `add_test_task=True` have
  independent config rows.
- All 9 PR 1b tests + 3 PR 2 tests are green on
  `--test-enable --stop-after-init`.

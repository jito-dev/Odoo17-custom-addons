# hr_recruitment_job_stage_config

Per-job stage configuration foundation for the stages-first recruitment
redesign. Implements **PR 1b** of `docs/recruitment_master_plan.md`.

## What this module does

Introduces a through-model `hr.job.stage.config` carrying payload on every
`(hr.job, hr.recruitment.stage)` edge. This is the foundation every later
PR in the roadmap builds on (per-job email templates, hidden stages,
per-job test-task description, call-stage booking link, named URL
resources).

Without this module, the standard Odoo `hr.recruitment.stage` is a single
global catalog with a `job_ids` M2M and global `template_id` — there is
no place to store per-job overrides. With it, every stage that needs a
job-specific value gets a row in `hr.job.stage.config` that carries:

- `sequence`, `visible` (per-job kanban order and visibility);
- `mail_template_id` (per-job email override, source of truth);
- `test_task_description`, `link_ids`, `booking_link_url`, `fold`,
  `color`, `legend_*`, `requirements`, `external_id_mapping`
  (reserved fields used by PR 3/4/5/Genio).

## Main models

| Model | Purpose |
|---|---|
| `hr.job.stage.config` | Through-model (job × stage) with payload. |
| `hr.job.stage.config.link` | Child model — per-(job × stage) named URLs. Reserved for PR 4. |
| `hr.recruitment.stage` (extended) | New `scope` Selection (`global` / `specific`) + revised `default_get`. |
| `hr.job` (extended) | `stage_config_ids` One2many, `hidden_stage_count` compute, `use_per_job_test_task_links` toggle (reserved). |
| `hr.applicant` (extended) | Overrides `_read_group_stage_ids`, `_compute_stage`, `_track_template`. |

## Business logic

- **Stage creation** from a job's kanban (`+ Stage`) defaults to
  `scope='specific'` with `job_ids=[current_job]` instead of the stock
  global behaviour. Replaces `hr_recruitment_stage_default_fix` with a
  fuller implementation; the standalone module remains compatible.
- **Kanban filtering** (`_read_group_stage_ids`) hides per-job-hidden
  stages but always keeps stages currently hosting applicants visible
  (R10 safety guarantee).
- **New applicant default stage** (`_compute_stage`) skips per-job
  hidden stages and honours `config.sequence` for ordering.
- **Email template tracking** (`_track_template`) resolves the template
  via `config.mail_template_id` → `stage.template_id` → no mail.

## Migration

`post_init_hook` (manifest) and `migrations/17.0.1.0.0/post-migrate.py`
share the same idempotent `run_backfill` function:

1. Snapshot `(applicant_id, stage_id)` for R2 drift verification.
2. Rename legacy `IQ Test Assigned/Completed` to
   `Cognitive Assessment Assigned/Completed` (skipped if target name
   already exists).
3. For every `hr.recruitment.stage` with `job_ids != []`, create
   `hr.job.stage.config` rows (`visible=True`, sequence and template
   copied from the stage as initial values). Idempotent via
   `search_count`.
4. Recompute the stored `scope` Selection.
5. Re-read the applicant snapshot and log either
   `R2 verification OK` or `R2 GUARANTEE BROKEN ...` to `ir.logging`.

## Constraints

- Only Odoo 17 APIs (`@api.depends`, `@api.constrains`, `_read_group`).
- Module is additive — uninstalling drops the config table and added
  fields; `hr_applicant`, `hr_recruitment_stage`, `hr_job` rows are
  untouched.
- `hired_stage` remains a global attribute on the stage. Per-job
  hired_stage is a known limitation and is reserved for a later PR
  (see master plan §9.1.2).
- The `booking_link_id` M2O to `calendar.appointment.type` is deferred
  to PR 5 (when its own module pulls in the `appointment` dependency).
  PR 1b only carries the `booking_link_url` Char fallback.

## Tests

Nine PR 1b tests under `tests/`:

| File | Risk addressed |
|---|---|
| `test_stage_scope.py` | scope compute / inverse, default_get |
| `test_kanban_filtering.py` | `_read_group_stage_ids` + R10 |
| `test_compute_stage_with_hidden.py` | R10 (new applicant on hidden stage) |
| `test_template_fallback.py` | R4 + R6 (template SoT, multi-company) |
| `test_migration_idempotent.py` | Re-install safety + IQ→Cognitive |
| `test_migration_multi_company.py` | R6 |
| `test_migration_zero_stages.py` | Empty-DB edge case |
| `test_concurrent_sequence_update.py` | R9 (drag reorder) |
| `test_post_migrate_logs_to_ir_logging.py` | Audit log presence |

Run from this module:

```bash
odoo-bin -c <conf> -i hr_recruitment_job_stage_config \
    --test-enable --stop-after-init --log-level=test
```

Or in the atomic-bundle release with PR 2:

```bash
odoo-bin -c <conf> -i hr_recruitment_job_stage_config,hr_recruitment_test_task \
    --test-enable --stop-after-init --log-level=test
```

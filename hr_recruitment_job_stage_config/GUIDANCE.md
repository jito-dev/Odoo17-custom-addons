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

## v17.0.1.0.6 — drop `default='global'` on `scope` (kanban "+ Stage" actually works now)

**Симптом (повторне розслідування):** після v17.0.1.0.5 з `precompute=True`
користувач все одно отримує **`scope='global'` І порожнє `job_ids`** при
створенні стейджу через kanban "+ Stage". Тести
`test_default_get_with_job_context_makes_stage_specific` та
`test_scope_persisted_as_specific_on_kanban_create` падають на
`assertIn(self.job_a, stage.job_ids)` — М2М порожня одразу після `create()`.

**Справжній корінь** (v17.0.1.0.5 GUIDANCE був неправильним щодо причини):

Послідовність у `super().create(vals_list)`:
1. Наш `create` override вставляє `vals['job_ids'] = [(6, 0, [job_id])]`.
2. `_prepare_create_values` → `_add_missing_default_values` викликає
   `default_get(missing_defaults)`. Поле `scope` має `default='global'`,
   тож `default_get` повертає `'global'`, і `vals['scope'] = 'global'`.
3. `_add_precomputed_values` ПРОПУСКАЄ `scope`, бо `'scope' in vals`
   (precompute fires тільки для відсутніх ключів).
4. `scope` НЕ потрапляє у `precomputed`-set, тому в основному циклі
   `create` (`models.py:4597`) `inversed['scope'] = 'global'`.
5. SQL INSERT з `scope='global'` та `job_ids=[X]` у relation-таблиці.
6. `_inverse_scope` запускається з `scope='global'` → виконує
   `stage.job_ids = [(5, 0, 0)]` → **видаляє щойно створений M2M-рядок**.
7. Як наслідок: post-super цикл бачить `stage.job_ids` порожнім → падає
   у `else`-гілку для глобальних стейджів → створює `hr.job.stage.config`
   для всіх вакансій з `visible=stage.default_visible_in_new_jobs` (зазвичай
   False) замість одного рядка для поточної вакансії з `visible=True`.

**Фікс:** прибрати `default='global'` з поля `scope`. Тепер
`_add_missing_default_values` не додає scope у vals → `_add_precomputed_values`
обчислює `scope` із `self.new(vals).job_ids` → `precomputed`-set містить
`scope` → `_inverse_scope` НЕ запускається після INSERT. Логіка
користувацького перемикача через форму не змінюється — `write({'scope':...})`
далі викликає inverse явно.

**Інваріант:** після `Stage.with_context(default_job_id=X).create({'name':...})`
- `stage.job_ids == hr.job(X)`;
- `stage.scope == 'specific'` (як у БД, так і в кеші);
- існує **рівно один** `hr.job.stage.config` рядок `(X, stage)` із
  `visible=True`.

**Інверс при ручному фліпі** (`stage.scope = 'global'`) працює як раніше:
поле явно у vals → inverse запускається → очищає `job_ids`.

**Сумісність:** міграція 17.0.1.0.6 ре-синхронізує `scope` для існуючих
рядків через ту саму `_recompute_scope`-функцію, яку ми вже використовуємо
в `post_init_hook`. Жодних деструктивних операцій.

## v17.0.1.0.5 — `precompute=True` on `scope` (PARTIAL — see 17.0.1.0.6)

> **СТАТУС:** недостатньо. `precompute=True` сам по собі не вирішив проблему,
> бо `default='global'` все одно потрапляв у `vals` через
> `_add_missing_default_values`, а precompute працює лише для ВІДСУТНІХ
> ключів. Повний фікс — у 17.0.1.0.6 (прибрати дефолт). Запис нижче
> залишаємо для історичної прозорості; не покладайтеся на нього як на
> повний опис root-cause.

**Симптом:** натискаєш «+ Stage» у kanban кандидатів конкретної вакансії —
у формі стейджу через шестерню видно `Scope: Global` замість `Specific`.

**Помилкова гіпотеза:** Odoo 17 (`models.py:4632`) захищає editable
computed-stored поля від перерахунку всередині `create()` — а `scope` має
`inverse=`, тож вважається editable. (Правильна частина: захист існує.
Неправильна частина: причина регресії не в захисті, а в тому, що
`_inverse_scope` запускається ПІСЛЯ INSERT і очищає `job_ids` — див.
17.0.1.0.6.)

## v17.0.1.0.2 — Auto-create config rows on stage.job_ids writes (PLANNED)

> **Статус:** PLAN — див. [`docs/recruitment_test_task_iq_stages_fix_plan.md`](../docs/recruitment_test_task_iq_stages_fix_plan.md).
> Запис нижче описує **очікувану інваріанту**, навіть якщо код ще не
> вмерджений. Інші модулі (`hr_recruitment_test_task`, `iq_tests_survey`)
> вже полагаються на цей контракт.

**Інваріанта foundation-модуля (after fix):**

Будь-який запис у `hr.recruitment.stage.job_ids` — через `write()`,
`create()`, ORM-команди `(4, id)` / `(6, 0, ids)` / `(3, id)` /
`(5, 0, 0)` — повинен **гарантувати** наявність `hr.job.stage.config`
рядка `(job_id, stage_id, visible=True)` для кожного newly-added job.
Це робить нинішня (і майбутня) інверсна логіка `_inverse_scope`
доступною також зовнішнім написам `job_ids`, які раніше пропускали
config-create і робили стейдж невидимим у kanban.

**Контракт для downstream-модулів:**

- Можна писати `stage.write({'job_ids': [(4, job.id)]})` напряму;
  foundation сам створить config-рядок з `visible=True`.
- Не потрібно (і не варто) дублювати `hr.job.stage.config.create`
  у власному модулі — single source of truth тут.
- Ручне `config.visible=False` ніколи не перетирається: idempotent
  create skip-ить наявні рядки.
- При видаленні job з `job_ids` config-рядок **НЕ видаляється** —
  applicant може там бути (R10 safety).

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

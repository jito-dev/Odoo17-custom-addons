# HR Recruitment — Stage default_get fix

## What the module does

Fixes a single localised problem in stock Odoo 17:

- **Before installing:** clicking "+ Stage" in the kanban board of a
  specific vacancy's candidates → the new stage is created with empty
  `job_ids` → it instantly becomes **global** and shows up in the kanban
  of every other vacancy.
- **After installing:** clicking "+ Stage" in the kanban board of a
  specific vacancy's candidates → the new stage is created with
  `job_ids = [current_vacancy]` → visible **only** in that vacancy.

Creating a stage from **Configuration → Recruitment → Stages** and
beyond is unchanged: `job_ids=[]`, stage is global (stock behaviour).

## Why this problem exists

In the stock
`odoo17_enterprise/odoo/addons/hr_recruitment/models/hr_recruitment_stage.py`:

```python
@api.model
def default_get(self, fields):
    if self._context and self._context.get('default_job_id') and not self._context.get('hr_recruitment_stage_mono', False):
        context = dict(self._context)
        context.pop('default_job_id')        # ← drops job_id from the context
        self = self.with_context(context)
    return super(RecruitmentStage, self).default_get(fields)
```

The stock logic deliberately drops `default_job_id` from the context
before super, so that a new stage is "global by default". The
`hr_recruitment_stage_mono` flag is an escape hatch, but the standard
UI never sets it anywhere. That is why **all** stages created from the
kanban ended up global.

A detailed root-cause analysis lives in
[`jito_modules/docs/recruitment_vacancy_stages_flow.md`](../docs/recruitment_vacancy_stages_flow.md) §4.

## How exactly the module fixes it

A single method override in `models/hr_recruitment_stage.py`:

```python
class RecruitmentStage(models.Model):
    _inherit = 'hr.recruitment.stage'

    @api.model
    def default_get(self, fields):
        res = super().default_get(fields)
        job_id = self._context.get('default_job_id')
        if (
            job_id
            and not self._context.get('hr_recruitment_stage_mono', False)
            and 'job_ids' in fields
            and not self._context.get('default_job_ids')
            and not res.get('job_ids')
        ):
            res['job_ids'] = [(6, 0, [job_id])]
        return res
```

In other words, the stock behaviour with `pop('default_job_id')` is
preserved in full — we just put `job_ids` back into the defaults
**after** super(), based on the context that our `self` retained before
super.

## Safety guarantees

- ❌ **No existing stage is modified.** The override only touches the
  `default_get` call — it does not write to the DB.
- ❌ **No new models / fields / tables / FKs.**
- ❌ **No migration** (no `migrations/`).
- ❌ **No view changes** (no `data` in the manifest).
- ❌ **No changes to `odoo17_enterprise/` / `odoo17_community/`.**

## Escape hatches (optional for integrations)

If another module deliberately wants to create a **global** stage from
a context that has `default_job_id`, there are two alternatives:

1. `with_context(hr_recruitment_stage_mono=True)` — uses the
   documented stock escape hatch.
2. `with_context(default_job_ids=[(6, 0, [...])])` — explicitly sets
   its own value for `job_ids`; our override respects it.

## Tests

`tests/test_default_get.py` — 7 cases:

1. `test_stage_from_kanban_is_job_specific` — +Stage from kanban sets
   `job_ids` to the current vacancy.
2. `test_stage_from_configuration_is_global` — without a job context
   `job_ids` stays empty.
3. `test_explicit_default_job_ids_respected` — an explicit
   `default_job_ids` from the caller is not overwritten.
4. `test_mono_flag_escape_hatch` — `hr_recruitment_stage_mono=True`
   restores the stock behaviour.
5. `test_full_create_flow_with_kanban_context` — end-to-end via
   `create()` with kanban context.
6. `test_existing_global_stages_unchanged` — an old global stage
   stays global after a new specific stage is created.
7. `test_default_get_without_job_ids_in_fields` — if fields does not
   request `job_ids`, the override adds nothing.

Run locally:

```bash
odoo-bin -c <conf> -i hr_recruitment_stage_default_fix \
    --test-enable --stop-after-init --log-level=test
```

## Rollback

```
Apps → HR Recruitment — Stage default_get fix → Uninstall
```

The DB state after uninstall is **identical** to the state before
install — nothing was written.

## Roadmap context

This is **PR 1a** of [`recruitment_master_plan.md`](../docs/recruitment_master_plan.md) —
the fastest and safest piece of the master plan. Closes a user-visible
bug without blocking the rest of the roadmap (per-job stage config,
hide stages, test task per job, call stage, form restructure — a
separate PR 1b and onwards).

After PR 1b (full foundation with the `hr.job.stage.config`
through-model) this module can either:
- **Stay** as a standalone fix (depend-friendly);
- **Be absorbed** into `hr_recruitment_job_stage_config` (depends → remove).

The decision about the module's fate is taken at the moment PR 1b is merged.

## Patterns / Constraints

- One model override, one file (per CLAUDE.md "one model per file").
- No demo data (per CLAUDE.md).
- Version `17.0.1.0.0` (new major, first minor for the module).
- LGPL-3, like the rest of jito_modules.

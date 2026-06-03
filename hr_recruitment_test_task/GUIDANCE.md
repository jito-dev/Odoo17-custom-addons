# HR Recruitment — Test Task

## What this module does

Adds an opt-in **technical test task** workflow for a `hr.job`:

- Toggle **Add Test Task** (`add_test_task`) on the job form.
- When `True`, three recruitment stages — **Test Task Given**,
  **Test Task Submitted**, **Test Task ChatGPT Analyzed** — become
  visible in the applicant kanban of that job (and only that job).
- An optional **Test Task Link** (`test_task_link`) appears inline
  next to the checkbox — a URL (e.g., GitHub repository) that the
  candidate can open to read the task specification. Rendered as
  an "Open Test Task" button in the invitation email, under a
  `Description:` header, **unique per vacancy**. Hidden from the
  email when empty. URL must start with `http://` or `https://`
  (`@api.constrains`).
- Candidates moved to **Test Task Given** receive an email with a
  unique submission portal URL (`/test-task/start?token=<uuid>`).
- Candidates submit their solution (GitHub link); module records each
  attempt as a `hr.test.submission` and surfaces the latest link on
  the applicant form.
- `Test Task Submitted` stage receives candidates after a successful
  POST from the portal; `Test Task ChatGPT Analyzed` is reserved for
  AI scoring (placeholder fold=True).

## Main models, views, business logic

| Model | File | Role |
|---|---|---|
| `hr.job` | `models/hr_job.py` | Adds `add_test_task` Boolean + `_manage_test_task_stages` orchestrator |
| `hr.applicant` | `models/hr_applicant.py` | Adds `test_task_token`, `submission_ids`, `last_github_link`, `ai_analysis_score`, `ai_analysis_summary`, `job_add_test_task` related field, `get_test_task_url` helper |
| `hr.test.submission` | `models/test_submission.py` | One-shot submission record (GitHub link, timestamp) |

Views: `views/hr_applicant_views.xml` (submission section in applicant
form), `views/hr_job_views.xml` (the `add_test_task` field on the job
form), `views/website_templates.xml` (the public portal).

Data: `data/mail_data.xml` (invite email template), `data/stage_data.xml`
(the three stages — created **global** by default, become specific to a
job only via the foundation auto-create — see below).

## How stage visibility works (important)

The three test-task stages live in the global catalogue
`hr.recruitment.stage`. When `add_test_task=True`, the job is added to
each stage's `job_ids` via `_manage_test_task_stages`:

```python
stages.write({'job_ids': [(4, self.id)]})
```

This module **deliberately does not** touch `hr.job.stage.config`. The
foundation module `hr_recruitment_job_stage_config` (≥ v17.0.1.0.2)
listens to `stage.job_ids` writes and auto-creates the corresponding
config row with `visible=True`. See
[`docs/recruitment_test_task_iq_stages_fix_plan.md`](../docs/recruitment_test_task_iq_stages_fix_plan.md)
for the analysis and the contract behind this delegation.

This split is intentional:

- **Single source of truth.** Only `hr_recruitment_job_stage_config`
  knows how to keep the `(job, stage)` config table in sync. Other
  modules just write to `stage.job_ids`.
- **No regression risk for hand-toggled visibility.** Idempotent
  create skips existing rows, so a recruiter who manually set
  `config.visible=False` is never overridden.
- **Forward compatibility.** Future modules that add stages on a
  toggle (e.g. "Add Call Stage", "Add Reference Check") get
  auto-visibility for free.

## When `add_test_task` is unset

`_manage_test_task_stages(False)` removes the job from `stage.job_ids`
(via `(3, self.id)`). The config row is **not** deleted — applicants
might still be on that stage. The stage just becomes hidden in this
job's kanban (default `visible=True` on a config row still applies
when a new job is added later, because we never deleted the row).

## Email template (mail_data.xml)

`mail.template` record `mail_template_test_task_invite` — referenced
by `stage_test_given` in `data/stage_data.xml` via
`<field name="template_id" ref="..."/>`. The `Test Task Given` stage
template is a **fallback default**; per-job overrides should live on
`hr.job.stage.config.mail_template_id` so two jobs can have different
test-task invites. Do not write to `stage.template_id` from this
module (the legacy "CRITICAL FIX" hack that did this was removed in
v17.0.1.0.4).

## Patterns / Constraints

- One model per file (per CLAUDE.md).
- No demo data (per CLAUDE.md).
- Bump the manifest version on each module change.
- LGPL-3.

## Module roadmap

This module is the subject of **PR 2** in
[`docs/recruitment_master_plan.md`](../docs/recruitment_master_plan.md).
Future incremental scope (PR 4) covers per-job test-task description
HTML on `hr.job.stage.config.test_task_description` and per-stage
resource links on `hr.job.stage.config.link_ids`. Both are reserved
fields in the foundation module today.

# Cognitive Assessments (IQ Tests Survey) Module — Developer Guide

## Naming convention — read this first

**Hard rule:** backend stays `iq_*` exactly as it has been. Do not rename
any model, field, method, XML ID, security group, URL route, or
ir.model.access entry from `iq_*` to anything else. Other modules,
mail templates, security records, and stored data already reference
these names — renaming would break the system.

| Layer | Naming | Rationale |
|---|---|---|
| **Backend** (model names, fields, methods, XML IDs, security groups, URL routes, ir.model.access, technical strings) | `iq_*` — **do not touch** | Historical and stable contract for other modules / API consumers / stored data. |
| **Frontend / UI** (field labels, view strings, menu items, survey title, email subject, stage names) | `Cognitive Assessment` / `Cognitive Assessments` | Branding decision — what recruiters and candidates actually see. |

Concrete backend symbols that must remain unchanged:
`iq.survey`, `iq.question`, `iq.user_input`, `iq.user_input.line`,
`add_iq_test`, `iq_survey_id`, `iq_access_token`, `iq_score`,
`iq_category`, `iq_input_id`, `_create_iq_test_infrastructure`,
`_get_iq_test_url`, `mail_template_iq_invite`, `group_iq_user`,
`group_iq_manager`, `module_category_iq_tests`, `model_iq_*`,
`access_iq_*`, `/iq-test/*` URL routes.

If you see a backend symbol named `cognitive_*` or a UI string still
saying "IQ Test", that is a bug worth filing — but **the fix is to
update the UI string, not to rename the backend symbol**.

## What the Module Does
Provides Raven's Progressive Matrices (RPM) cognitive-assessment functionality for two use cases:
1. **Recruitment**: Automatically generate and assign cognitive assessments to job applicants, with token-based secure public access. Backend code paths remain `iq_*`; everything the recruiter or candidate sees says "Cognitive Assessment".
2. **Internal Employees**: Admins set a survey's Access Mode to "Internal for Employees". Any employee with the `group_iq_user` role can self-serve — they see the test in **My Cognitive Assessments** (menu XML ID `menu_my_iq_tests` — backend `iq`, frontend "Cognitive") and start it on demand. No individual assignment needed.

---

## Roles
| Group | XML ID | Access |
|-------|--------|--------|
| IQ Tests User | `iq_tests_survey.group_iq_user` | See "My IQ Tests" menu, take internal tests, view own results (read-only) |
| IQ Tests Administrator | `iq_tests_survey.group_iq_manager` | Full access: manage surveys, all results |

The Administrator group implies User. Both are under the "IQ Tests" Settings category.

---

## Main Models
| Model | File | Description |
|-------|------|-------------|
| `iq.survey` | `models/iq_survey.py` | Test definition: title, questions, access mode, statistics, per-employee status |
| `iq.question` | `models/iq_question.py` | Individual question: image file, correct answer (1–8) |
| `iq.user_input` | `models/iq_user_input.py` | Test session: answers, IQ score, state (pending/done) |
| `iq.user_input.line` | `models/iq_user_input.py` | Per-question answer record |

---

## Business Logic

### Recruitment Flow
1. HR enables **"Add Cognitive Assessment"** on a job (`add_iq_test=True` on `hr.job`) → system auto-creates `iq.survey` + two stages.
2. The two stages — **Cognitive Assessment Assigned** and **Cognitive Assessment Completed** — become visible in this job's applicant kanban (and only this job's). The "Assigned" stage carries the `mail_template_iq_invite` email template **as a per-job override on `hr.job.stage.config.mail_template_id`**, not on the global `stage.template_id`.
3. Applicant reaches "Cognitive Assessment Assigned" stage → email sent with `?token=<iq_access_token>`.
4. Applicant opens public URL → completes test → `iq.user_input` created → applicant moves to "Cognitive Assessment Completed".

> **Stage visibility contract.** Adding the job to `stage.job_ids` is enough — the foundation module `hr_recruitment_job_stage_config` (≥ v17.0.1.0.2) auto-creates the `hr.job.stage.config` row with `visible=True`. Do **not** write to `stage.template_id` for per-job overrides — it is a global field shared by every job that uses the stage; use the per-job config row instead. See [`docs/recruitment_test_task_iq_stages_fix_plan.md`](../../docs/recruitment_test_task_iq_stages_fix_plan.md) for the full rationale.

### Internal Employee Flow
1. Admin creates an `iq.survey` with `access_mode = 'internal'`.
2. Employee with `group_iq_user` opens **My IQ Tests** → sees all internal surveys with personal status.
3. Employee clicks **Take Test** → `action_employee_start_test()` runs:
   - Finds the employee record for `env.uid`
   - Creates a pending `iq.user_input` with UUID `access_token` (or reuses existing pending one)
   - Redirects browser to `/iq-test/go/{slug}?etoken={token}` in a new tab
4. Employee fills name + age, completes test → `iq.user_input` updated to `state='done'` with score.
5. Employee clicks **View Result** in "My IQ Tests" → opens result page.

---

## Key Patterns & Constraints

### Access Modes on `iq.survey`
- `token` — recruitment-only (requires `?token=` URL param)
- `email` — email-based open access
- `internal` — self-serve for authenticated employees with `group_iq_user`

### Token Types
- `?token=` — applicant token (stored on `hr.applicant.iq_access_token`)
- `?etoken=` — employee token (stored on `iq.user_input.access_token`)

### `iq.user_input.state`
- `pending` — test session created but not yet taken (internal employee flow)
- `done` — test completed and scored (default for all records; all legacy records treated as done)

### Security (Row-Level)
- `group_iq_user` can only read `iq.user_input` rows where `employee_id.user_id = current user`.
- `group_iq_user` sees `iq.survey` records (all), but "My IQ Tests" action filters to `access_mode='internal'`.
- Public users (recruitment flow) bypass the group system via explicit public ACL lines.

### Per-Employee Computed Fields on `iq.survey`
`employee_test_state`, `employee_iq_score`, `employee_iq_category`, `employee_input_id` are computed with `@api.depends_context('uid')` — not stored. Each user sees their own status.

### `action_employee_start_test()`
Uses `sudo()` to create `iq.user_input` on behalf of the employee (bypasses read-only ACL for `group_iq_user`). Always checks for existing done/pending records before creating new ones.

---

## File Structure
```
iq_tests_survey/
├── __manifest__.py          (version 17.0.1.2.0)
├── hooks.py                  Post-install: creates 60 questions
├── controllers/
│   └── main.py               Public web routes for test flow
├── models/
│   ├── iq_survey.py          IQ Survey model (+ per-employee computed fields + action_employee_start_test)
│   ├── iq_question.py        IQ Question model
│   ├── iq_user_input.py      Test session + answer lines
│   ├── hr_job.py             hr.job extension
│   └── hr_applicant.py       hr.applicant extension
├── security/
│   ├── iq_security.xml       Security groups + all ACL records (consolidated XML)
│   └── iq_record_rules.xml   Row-level access rules
├── views/
│   ├── iq_backend_views.xml  Survey + Results backend views
│   ├── iq_my_tests_views.xml "My IQ Tests" employee view (survey-based, with status columns)
│   ├── iq_menus.xml          Menu definitions (role-gated)
│   ├── iq_frontend_templates.xml  Public web templates
│   ├── hr_job_views.xml
│   └── hr_applicant_views.xml
└── data/
    ├── iq_data.xml           Initial survey record
    └── mail_data.xml         Email template (recruitment only)
```

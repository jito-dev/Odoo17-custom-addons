# IQ Tests Survey Module — Developer Guide

## What the Module Does
Provides Raven's Progressive Matrices (RPM) IQ test functionality for two use cases:
1. **Recruitment**: Automatically generate and assign IQ tests to job applicants, with token-based secure public access.
2. **Internal Employees**: Admins set a survey's Access Mode to "Internal for Employees". Any employee with the `group_iq_user` role can self-serve — they see the test in **My IQ Tests** and start it on demand. No individual assignment needed.

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
1. HR enables "Add IQ Test" on a job → system auto-creates `iq.survey` + stages.
2. Applicant reaches "IQ Test Assigned" stage → email sent with `?token=<iq_access_token>`.
3. Applicant opens public URL → completes test → `iq.user_input` created → applicant moves to "IQ Test Completed".

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

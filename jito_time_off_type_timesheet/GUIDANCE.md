# jito_time_off_type_timesheet — Module Guidance

## Purpose

This module fixes three issues with the Enterprise `project_timesheet_holidays` module:

1. **Hidden timesheet section**: The "Timesheets" configuration group on the
   Time Off Type form is restricted to developer mode (`groups="base.group_no_one"`).
   HR managers cannot configure which task to use for timesheet generation.

2. **Circular compute dependency**: Checking "Generate Timesheets" auto-sets
   `timesheet_project_id`, which re-triggers `_compute_timesheet_generate`,
   which finds no task yet and immediately resets the checkbox to `False`.

3. **Global leave types inaccessible**: For global leave types (no `company_id`),
   `timesheet_project_id` is always `False` and `timesheet_generate` is always
   `True`. Because the task field was conditioned on `timesheet_project_id`, the
   task field was permanently hidden. Users couldn't configure tasks on any
   globally-shared leave type (e.g. pre-installed Sick Leave, Annual Leave).

## Main Components

### `models/hr_leave_type.py` — `HolidaysType` (inherits `hr.leave.type`)

**`timesheet_project_for_task`** (new non-stored computed field)
- Returns `timesheet_project_id` if set, otherwise `env.company.internal_project_id`.
- Used exclusively by the view for task field domain, quick-create context, and visibility.
- Does **not** change any stored field; has no side effects on Enterprise logic.
- Fixes global leave types: even when `timesheet_project_id = False`, this field
  resolves to a real project, so the task field becomes visible and functional.

**`_compute_timesheet_generate`** (override)
- Original `@api.depends`: `timesheet_task_id`, `timesheet_project_id`
- New `@api.depends`: `timesheet_task_id`, `company_id` (project removed)
- Semantics: `True` when no company (global type) or task is set.
- Removing the project dependency prevents the circular reset loop.

**`_onchange_timesheet_generate`** (new)
- When user checks the box: auto-fills `timesheet_project_id` with
  `company_id.internal_project_id` (or `env.company.internal_project_id` for
  global types as fallback), but only if not already set.
- When user unchecks: clears both `timesheet_project_id` and `timesheet_task_id`.

### `views/hr_leave_type_views.xml`

Inherits `project_timesheet_holidays.hr_holiday_status_view_form_inherit` and
uses `position="replace"` on `//group[@name='timesheet']`.

Key changes vs. Enterprise original:
| Field | Original | This module |
|---|---|---|
| `<group name="timesheet">` | `groups="base.group_no_one"` | No restriction |
| `timesheet_project_id` | Visible when company set | `invisible="1"` (auto-managed) |
| `timesheet_project_for_task` | — | `invisible="1"` (helper, used in domain/context) |
| `timesheet_generate` | `invisible="company_id"` | Always visible |
| `timesheet_task_id` | `invisible="not timesheet_project_id"` | `invisible="not timesheet_generate"` |
| `timesheet_task_id` domain | `project_id = timesheet_project_id` | `project_id = timesheet_project_for_task` |
| `timesheet_task_id` context | `default_project_id: timesheet_project_id` | `default_project_id: timesheet_project_for_task` |

## UX Flow

### Company-scoped leave type
1. HR manager opens a Time Off Type form (no developer mode needed).
2. Checks **"Generate Timesheets"** → onchange silently sets
   `timesheet_project_id = company.internal_project_id` (hidden); task dropdown appears.
3. Manager selects an existing task **or types a new name** — quick-create creates
   the task inside the Internal project (via `default_project_id` context).
4. Save → `_check_timesheet_generate` constraint confirms both project and task.
5. Validating a leave of this type generates `account.analytic.line` records.

### Global leave type (no company_id) — existing or new
1. HR manager opens the form — `timesheet_generate` is already `True` (always).
2. **Task field is immediately visible** (no checkbox interaction needed).
3. `timesheet_project_for_task` resolves to `env.company.internal_project_id`.
4. Manager selects or quick-creates a task in that Internal project.
5. Save — no constraint error (constraint only fires for company-scoped types).
6. Note: Enterprise `_validate_leave_request` still uses `employee.company_id`
   settings for global types at leave-validation time. The task stored here is
   visible for reference (e.g. Payroll for Contractors task identification).

## Constraints & Invariants

- `_check_timesheet_generate` (Enterprise, unchanged) fires on save and raises
  `ValidationError` if `timesheet_generate=True` and project/task missing for
  a **company-scoped** type. Global types are exempt.
- `timesheet_project_for_task` is non-stored; it never affects DB or business logic.
- No new models; no security CSV needed.

## Dependencies

- `project_timesheet_holidays` (Odoo Enterprise)

## Testing

1. **Existing global type** (e.g. Sick Leave): open form → task field visible immediately
   → type new task name → quick-creates in Internal project → save → no error.
2. **Existing company type, no task**: open form → checkbox unchecked → check it
   → task field appears → select/create task → save.
3. **Existing company type, task already set**: open form → task field visible →
   change task → save → task updated.
4. **New type (any)**: create → configure → save → works same as existing.
5. Uncheck "Generate Timesheets" → project and task clear → save.

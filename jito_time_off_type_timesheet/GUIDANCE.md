# jito_time_off_type_timesheet — Module Guidance

## Purpose

This module fixes two issues with the Enterprise `project_timesheet_holidays` module:

1. **Hidden timesheet section**: The "Timesheets" configuration group on the
   Time Off Type form is restricted to developer mode (`groups="base.group_no_one"`).
   HR managers cannot configure which task to use for timesheet generation.

2. **Circular compute dependency**: Checking "Generate Timesheets" auto-sets
   `timesheet_project_id`, which re-triggers `_compute_timesheet_generate`,
   which finds no task yet and immediately resets the checkbox to `False`.

## Main Components

### `models/hr_leave_type.py` — `HolidaysType` (inherits `hr.leave.type`)

**`_compute_timesheet_generate`** (override)
- Original `@api.depends`: `timesheet_task_id`, `timesheet_project_id`
- New `@api.depends`: `timesheet_task_id`, `company_id` (project removed)
- Semantics unchanged: `True` when no company (global type) or task is set.
- Breaking the project dependency prevents the circular reset loop.

**`_onchange_timesheet_generate`** (new)
- When user checks the box + company is set → auto-fills `timesheet_project_id`
  with `company_id.internal_project_id`.
- When user unchecks → clears both `timesheet_project_id` and `timesheet_task_id`.

### `views/hr_leave_type_views.xml`

Inherits `project_timesheet_holidays.hr_holiday_status_view_form_inherit` and
uses `position="replace"` on `//group[@name='timesheet']`.

Key changes vs. Enterprise original:
| Field | Original | This module |
|---|---|---|
| `<group name="timesheet">` | `groups="base.group_no_one"` | No restriction |
| `timesheet_project_id` | Visible when company set | Always `invisible="1"` |
| `timesheet_generate` | `invisible="company_id"` (hidden for company types) | Always visible |
| `timesheet_task_id` | `invisible="not timesheet_project_id"` | `invisible="not timesheet_generate or not company_id"` |

## UX Flow

1. HR manager opens a Time Off Type form (no developer mode needed).
2. Checks **"Generate Timesheets"** → checkbox stays checked; onchange silently
   sets Internal project; "Timesheet Task" dropdown appears.
3. Manager selects an existing task or types a new name (quick-create assigns
   it to Internal project via `default_project_id` context).
4. Save → `_check_timesheet_generate` constraint confirms both project and task.
5. Validating a leave of this type generates `account.analytic.line` records.

## Constraints & Invariants

- `_check_timesheet_generate` (from Enterprise, unchanged) fires on save and
  raises a `ValidationError` if `timesheet_generate=True` and either project
  or task is missing for a company-scoped leave type.
- Global leave types (`company_id = False`) always have `timesheet_generate=True`
  and use the employee's company project/task at validation time.
- This module adds no new models, no security CSV is needed.

## Dependencies

- `project_timesheet_holidays` (Odoo Enterprise)

## Testing

1. Install: `./odoo-bin -u jito_time_off_type_timesheet`
2. Open **Time Off → Configuration → Time Off Types** (no developer mode).
3. Verify "Timesheets" section is visible.
4. Check "Generate Timesheets" → checkbox stays checked, task dropdown appears.
5. Type a new task name → quick-create assigns it to Internal project.
6. Save → no constraint error.
7. Submit and validate a leave → confirm timesheet entry created.
8. Uncheck → project/task clear; save succeeds.

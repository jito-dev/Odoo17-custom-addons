# jito_public_holiday_timesheet — Module Guidance

## Purpose

Routes public holiday timesheet generation to a **dedicated task** ("Public Holidays")
instead of the generic "Time Off" task, and uses the actual holiday name in the
timesheet description.

| Scenario | Before this module | After this module |
|---|---|---|
| Public holiday timesheet task | "Time Off" | "Public Holidays" |
| Public holiday description | "Time Off (1/1)" | "Christmas Day (1/1)" |
| Regular leave timesheet | "Time Off (1/3)" | unchanged |

## Depends On

- `project_timesheet_holidays` (Odoo Enterprise bridge between leaves and timesheets)

## Main Models & Fields

### `res.company` (`models/res_company.py`)
- **`public_holiday_timesheet_task_id`** (`Many2one → project.task`): The task
  used for public holiday timesheets. Constrained to tasks inside the company's
  `internal_project_id`. If left empty, the module falls back to the standard
  "Time Off" task.
- **`_create_internal_project_task()`**: Overridden to also create the "Public
  Holidays" task whenever a new internal project is set up for a company.

### `res.config.settings` (`models/res_config_settings.py`)
- Exposes `public_holiday_timesheet_task_id` (via `related`) so admins can
  configure it from **Settings → Timesheets**.

### `resource.calendar.leaves` (`models/resource_calendar_leaves.py`)
- **`_timesheet_prepare_line_values()`**: Overridden to inject:
  - `task_id` → `public_holiday_timesheet_task_id` (when configured)
  - `name`    → `"<Holiday name> (x/y)"` (e.g. `"Christmas Day (1/1)"`)
  - Falls back to parent behaviour when the field is not set.

## Business Logic Flow

1. A public holiday (`resource.calendar.leaves`) is created or modified.
2. Odoo calls `_generate_timesheeets()` → `_timesheet_create_lines()`.
3. For each employee work-day inside the holiday, `_timesheet_prepare_line_values()`
   is called — our override kicks in and substitutes the task and description.
4. The resulting `account.analytic.line` records carry `global_leave_id` linking
   back to the public holiday (unchanged from base behaviour).

## Setup & Installation

- Install the module; the `post_init` hook automatically creates the "Public
  Holidays" task in each company's Internal project and assigns it.
- After install, verify/configure the task at:
  **Settings → Timesheets → Time Off → Public Holidays Task**

## Constraints & Notes

- Existing timesheet entries created *before* this module was installed retain
  their original task and description. To re-generate them, edit and re-save
  the affected public holiday record (Odoo will unlink old entries and rebuild).
- Only `resource.calendar.leaves` with no `resource_id` (i.e. company-wide
  global leaves) generate timesheets — individual resource leaves do not.
- The module never touches regular `hr.leave` time-off timesheets.

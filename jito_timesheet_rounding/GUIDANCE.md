# jito_timesheet_rounding — Developer Guidance

## What this module does

Two independent features, both scoped to timesheets:

1. **Company hours tracking rounding** — a per-company setting that requires
   Hours Spent (`account.analytic.line.unit_amount`) to be a multiple of 15 or
   30 minutes. Nothing is ever rounded silently: a non-conforming duration is
   rejected with a message asking the user to fix it.
2. **XLSX export of Adjusted Hours as a duration** — `tm_adjusted_hours` leaves
   the standard `Action → Export → .xlsx` with the Excel `[h]:mm` number format,
   so 1 h 10 min reads as `01:10` instead of the ambiguous `1.17`.

---

## The rule applies to new entries only

This is the module's central constraint, and the reason it was reworked in
2.0.0. **Entries that existed before the rule was switched on are out of its
reach entirely.** They are never validated, never converted, never blocked:

- enabling the setting changes no stored value;
- an existing off-grid entry can be edited freely — description, task, project,
  and the duration itself, to any value including another off-grid one;
- there is no bulk conversion tool, and there must not be one. Version 1.x
  shipped a preview-and-confirm wizard for the ~3 775 legacy off-grid entries;
  it was removed when the requirement changed. Do not reintroduce it without
  that decision being revisited.

### How the boundary is decided

`res.company.timesheet_rounding_start_date` is stamped **the first time**
rounding is enabled on that company. An entry is covered when
`create_date >= timesheet_rounding_start_date`.

Details that matter:

- **The stamp comes from `cr.now()`, not `fields.Datetime.now()`.** `cr.now()`
  is the transaction clock Odoo fills `create_date` from
  (`models.py::_prepare_create_values`), so the comparison is exact.
  `Datetime.now()` truncates microseconds and would make the boundary fuzzy by
  up to a second.
- **`>=`, not `>`.** An entry created in the very transaction that enables the
  rule counts as new. Stricter, and the only self-consistent choice given both
  timestamps share a clock.
- **Stamped in `res.company.write()`/`create()`, not in
  `res.config.settings.set_values()`.** Every path that switches the setting on
  has to stamp it — the settings screen, a direct write, a data file, a test. A
  company with the setting on and no date would silently validate nothing.
- **Never overwritten.** Only companies whose date is empty receive one, so
  disabling and re-enabling keeps the original boundary. Moving it forward
  would drag entries logged in between into the rule retroactively.
- **Missing date means "validate nothing"** (`_timesheet_rounding_start()`
  returns `False`). That is the fail-safe direction: the business rule is that
  historical entries must never be blocked, so an unstamped company leaves
  everything alone rather than enforcing the grid across all history.
- **Per company**, like the step itself.

### Upgrading from 1.x

`migrations/17.0.2.0.0/post-migrate.py` stamps the upgrade moment on every
company that already had the setting on. Without it those companies would come
out of the upgrade enabled but unstamped — which, by the fail-safe above, means
the grid silently stops being enforced. The upgrade moment is the right
boundary: everything logged up to it predates the new rule.

A 1.x database also holds the removed wizard's view records. Odoo drops them
when this module is upgraded, but a sibling module whose views load *earlier* in
the same run can be validated against the stale child view first, and fail with
`Element '<xpath expr="//header">' cannot be located in parent view` — the
`<header>` that `tm_rate_card` used to declare is gone. If an upgrade hits that,
delete the two orphaned `ir.ui.view` rows
(`view_hr_timesheet_line_tree_inherit_rounding`,
`view_timesheet_rounding_wizard_form`) with their `ir.model.data` rows and run it
again.

### Deliberate boundaries between the two features

| | Hours Spent (`unit_amount`) | Adjusted Hours (`tm_adjusted_hours`) |
|---|---|---|
| XLSX format | untouched, stays decimal | `[h]:mm` |
| Grid validation | enforced, new entries only | **not** enforced |
| Values changed automatically | never | never |

Adjusted Hours is a billing correction, not tracked time — a PM legitimately
enters 1:10 there. Putting it on a 15/30-minute grid would break that workflow,
so the grid applies to tracked time only.

⚠️ **Mixed units in one sheet.** Excel durations are fractions of a day, decimal
hours are not. After this module, an exported sheet holds Hours Spent in hours
(`1.25`) and Adjusted Hours as a day fraction (`0.052083`, displayed `01:15`).
Each column sums correctly on its own, but a cross-column formula
(`=B2-C2`, "how much was adjusted") compares different units and yields nonsense.
This was an accepted trade-off, not an oversight.

---

## Main models and where things live

### `res.company`
- `timesheet_rounding_enabled` (Boolean), `timesheet_rounding_step` (`15` / `30`),
  `timesheet_rounding_start_date` (Datetime)
- `_timesheet_rounding_minutes()` — the step in minutes, or `0` when disabled
- `_timesheet_rounding_start()` — the boundary, or `False` when nothing is covered
- `create()` / `write()` — stamp the boundary on first enable

Every other component asks these methods rather than reading the fields.

### `res.config.settings`
Related fields plus `set_values()`, which **aligns the timer with the step** —
see "Timer" below. The boundary is exposed read-only: it is shown so an admin can
see what the rule covers, not so they can move it.

### `account.analytic.line`
- `_timesheet_rounding_step()` — step for this line, `0` when not applicable
- `_is_new_for_rounding()` — `create_date` against the company boundary
- `_check_timesheet_rounding()` — raises `ValidationError` off-grid, for covered lines
- `create()` validates every new line
- `write()` validates **only covered lines whose `unit_amount` actually changes**

### `models/rounding.py`
Pure helpers (`is_on_grid`, `steps_in`, `hours_to_excel_duration`) with no ORM
access, so they are unit-testable and shared by models and controller. There is
deliberately no `round_to_grid`: nothing in this module ever computes a corrected
duration.

### `controllers/export_xlsx.py`
Overrides the core `/web/export/xlsx` controller.

---

## Patterns and constraints worth knowing

### Validation scope: timesheets only
`account.analytic.line` also stores plain analytic entries created by invoicing
and accounting, where `unit_amount` is a **quantity, not a duration**. Validating
those against an hours grid would break accounting. `_timesheet_rounding_step()`
therefore returns `0` when `project_id` is not set. Do not remove that guard.

### Why `write()` and not `@api.constrains`
A constraint fires on every write touching `unit_amount`, with no access to the
previous value. Two things depend on having it:

- the boundary check needs the record, not just the new value;
- an unrelated edit (description, task) on an off-grid entry must not raise.

`write()` compares old and new values, filters to the covered records, and
validates only what genuinely changed.

### Escape hatch
`with_context(skip_timesheet_rounding_check=True)` bypasses the check, for
automated flows that own the duration (leave allocation, data fixes, historical
imports). Never set it from the UI.

### Timer
`timesheet_grid` rounds every timer stop **up** to
`timesheet_grid.timesheet_rounding` minutes, with `timesheet_min_duration` as a
floor (`timer/models/timer_mixin.py:_timer_rounding`). Both are **global system
parameters**, not per-company ones, and they are read from six different places
in `timesheet_grid`.

Rather than override all six, `set_values()` writes the company step into both
parameters when rounding is enabled. The timer keeps the visible round-up
behaviour Odoo always had, only on the right grid, so stopping it always yields
a valid entry and no new dialog is needed.

> **Limitation:** those parameters are global. With several companies on
> different steps, the last saved one wins for the timer. When rounding is
> disabled the parameters are left untouched.

### The export override
The core exporter picks a cell format from the **Python type** of the value
(`ExportXlsxWriter.write_cell`), so every float becomes `#,##0.00`. And
`from_data()` receives only column *labels* — the field names are gone by then.

So `base()` is overridden to resolve the duration column indexes from the export
payload while it is still available, and hands them over on the `request` object.
Scope is strictly `DURATION_FIELDS` (currently `account.analytic.line` /
`tm_adjusted_hours`); every other model and column keeps stock behaviour.

Two traps in the core writer to respect when editing this:
- `write_cell` does `cell_style = self.base_style` and then **mutates it** with
  `set_num_format`. Reusing the base styles leaks formats between columns, which
  is why this module allocates its own `duration_style`.
- Grouped exports go through `from_group_data`/`GroupExportXlsxWriter`, a
  different class. Both are overridden, including the per-group subtotal, so a
  grouped export does not print a decimal subtotal above duration rows.

### Prerequisite: `tm_rate_card` ≥ 1.14.8
Before that version `tm_adjusted_hours` was declared `digits='Hours'`, an
unregistered `decimal.precision` that silently resolved to 2 digits and rounded
every write. Entries stored then hold `1.17` instead of `1.1666…`. The `[h]:mm`
format still renders those as `01:10`, but **sums stay wrong** (three 00:40
entries total 02:01). The export format fixes presentation only; the underlying
numbers in those legacy rows stay wrong, and by the same "do not modify existing
entries" rule there is no repair tool — see `tm_rate_card/GUIDANCE.md`.

---

## Tests

| file | covers |
|---|---|
| `test_rounding_validation.py` | 15/30-minute accept/reject sets, disabled setting, writes on covered entries, escape hatch, non-timesheet analytic lines exempt — plus `TestExistingEntriesUntouched`: legacy entries editable to any duration, values never changed, no bulk entry point left |
| `test_rounding_boundary.py` | stamping on create/write, re-enable keeps the original boundary, multi-company write, entry exactly at the boundary, enabled-without-a-date fail-safe, boundary is per company |
| `test_export_format.py` | 00:20 / 00:40 / 01:10 / 01:15 round trip, `[h]:mm` registered in the workbook, Hours Spent still decimal, sums correct, column resolution scoped to timesheets |

`create_date` comes from `cr.now()`, so **every record a test creates shares one
timestamp**. Tests never try to age a record; they move the company boundary
instead. `tests/common.py` provides `_enable_rounding_for_new_entries()` (boundary
one second in the past) and `_enable_rounding_after_existing_entries()` (one
second in the future), plus `_existing_timesheet()` which builds a legacy entry
the way production did — logged while the rule was off, boundary stamped after.

The export tests build a real workbook with the real writer and read it back out
of the `.xlsx` zip (`xl/styles.xml`, `xl/worksheets/sheet1.xml`) — `openpyxl` is
not installed in this environment and `xlsxwriter` cannot read.

Run them with:

```
odoo-bin -d <db> -i jito_timesheet_rounding --test-enable \
         --test-tags /jito_timesheet_rounding --stop-after-init
```

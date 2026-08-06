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

Plus a manual bulk wizard that converts hand-picked legacy entries to the
configured step.

---

## Deliberate boundaries

| | Hours Spent (`unit_amount`) | Adjusted Hours (`tm_adjusted_hours`) |
|---|---|---|
| XLSX format | untouched, stays decimal | `[h]:mm` |
| Grid validation | enforced | **not** enforced |
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
- `timesheet_rounding_enabled` (Boolean), `timesheet_rounding_step` (`15` / `30`)
- `_timesheet_rounding_minutes()` — the step in minutes, or `0` when disabled.
  Every other component asks this method rather than reading the fields.

### `res.config.settings`
Related fields plus `set_values()`, which **aligns the timer with the step** —
see "Timer" below.

### `account.analytic.line`
- `_timesheet_rounding_step()` — step for this line, `0` when not applicable
- `_check_timesheet_rounding()` — raises `ValidationError` off-grid
- `create()` validates every new line
- `write()` validates **only the lines whose `unit_amount` actually changes**
- `action_open_timesheet_rounding_wizard()` — opens the bulk wizard

### `timesheet.rounding.wizard` (+ `.line`)
Preview-then-confirm bulk conversion. `new_value` is computed from
`wizard_id.rounding_method`, so switching between down/up/nearest updates the
whole preview live. `action_apply()` writes with a plain `write()`, so access
rights, record rules and the validated-timesheet guards all stay in force.

`is_blocked` / `blocked_reason` mark the entries reported in the preview but
never converted — validated ones, and **invoiced** ones (see below). Blocked rows
stay visible on purpose: the user has to see what was skipped and why.

### `controllers/export_xlsx.py`
Overrides the core `/web/export/xlsx` controller.

### `models/rounding.py`
Pure helpers (`is_on_grid`, `round_to_grid`, `hours_to_excel_duration`) with no
ORM access, so they are unit-testable and shared by models, wizard and controller.

---

## Patterns and constraints worth knowing

### Validation scope: timesheets only
`account.analytic.line` also stores plain analytic entries created by invoicing
and accounting, where `unit_amount` is a **quantity, not a duration**. Validating
those against an hours grid would break accounting. `_timesheet_rounding_step()`
therefore returns `0` when `project_id` is not set. Do not remove that guard.

### Why `write()` and not `@api.constrains`
About a third of the existing entries predate the setting and are off-grid (3 775
of 12 448 when the module was written). A constraint would fire on every write
touching `unit_amount` and make those rows uneditable — nobody could fix a
description or move them to another task. `write()` compares old and new values
and only validates rows where the duration genuinely changes. The wizard is the
supported way to convert them.

### The wizard is created server-side — do not move it back to `default_get`
`action_open_timesheet_rounding_wizard()` creates the wizard **with its preview
lines** and opens it by `res_id`.

Building the lines as `(0, 0, {...})` commands in `default_get` looks equivalent
and is not. The web client keeps values only for fields declared in the view
(`activeFields`, `relational_model/record.js` `_parseServerValues`), and
`timesheet_id` is not rendered — so it was dropped on the way to the browser and
never came back, and confirming the wizard failed with *"a mandatory field is not
set"*. The preview still looked correct, because the related columns are computed
server-side during `onchange`.

Two more reasons the server-side path is the right one:
- **Scale.** The main use for this wizard is converting the several thousand
  legacy off-grid entries. Every `CREATE` command raises the client's page limit
  to fit (`static_list.js`), so the whole selection would render at once with no
  pagination. Persisted lines paginate like any list.
- **Trust.** Record ids never leave the server.

The view still declares `<field name="timesheet_id" column_invisible="1"
force_save="1"/>` as a safety net for callers that go through `default_get`.
Both attributes are needed — `column_invisible` to keep the field in
`activeFields`, `force_save` to exempt it from the readonly filter applied on
save (`record.js` `_getChanges`). `test_view_keeps_timesheet_id_savable` guards
them.

### Invoiced entries are never converted
`action_apply()` writes `unit_amount`. `tm_rate_card` reacts by syncing
`tm_adjusted_hours` — and it does so with `_syncing_adjusted_hours=True`, the
exact flag its own *"locked once billed"* guard skips
(`tm_rate_card/models/account_analytic_line.py`). Converting an invoiced entry
would therefore rewrite billed hours silently.

`_compute_blocked` keeps those entries out of `action_apply()` entirely, using
the same rule as the Re-sync action in `tm_rate_card`: blocked when
`timesheet_invoice_id` is set and the invoice is not cancelled. Hence the
`sale_timesheet` dependency, which `tm_rate_card` uses but never declared.

> This closes the wizard's path to that hole. The underlying auto-sync bypass in
> `tm_rate_card` is untouched — it is still reachable by editing Hours Spent on
> an invoiced, non-validated entry by hand. Changing it affects live billing
> behaviour and needs its own decision.

### Escape hatch
`with_context(skip_timesheet_rounding_check=True)` bypasses the check, for
automated flows that own the duration (leave allocation, data fixes). Never set
it from the UI.

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
entries total 02:01). The export format fixes presentation; only the
`tm_rate_card` fix makes the underlying numbers right, and legacy rows need the
"Re-sync Adjusted Hours" action there.

### List header button
`tm_rate_card` already declares a `<header>` on `hr_timesheet.hr_timesheet_line_tree`.
The list arch parser keeps only the **last** `<header>` it meets
(`web/static/src/views/list/list_arch_parser.js`), so this module appends its
button into the existing one instead of declaring a second header. Declaring a
second one would silently remove the rate-card button.

---

## Tests

`tests/` covers every scenario from the specification:

| file | covers |
|---|---|
| `test_rounding_validation.py` | 15/30-minute accept/reject sets, disabled setting, existing entries untouched and still editable, non-timesheet analytic lines exempt |
| `test_rounding_wizard.py` | how the wizard is built (server-side lines, `default_get` fallback, view safety net), preview, nothing written before confirmation, down/up/nearest, only selected entries affected, wizard requires the setting |
| `test_wizard_blocked.py` | validated and invoiced entries reported but never converted, invoiced Adjusted Hours left intact, cancelled invoice does not block |
| `test_export_format.py` | 00:20 / 00:40 / 01:10 / 01:15 round trip, `[h]:mm` registered in the workbook, Hours Spent still decimal, sums correct, column resolution scoped to timesheets |

The export tests build a real workbook with the real writer and read it back out
of the `.xlsx` zip (`xl/styles.xml`, `xl/worksheets/sheet1.xml`) — `openpyxl` is
not installed in this environment and `xlsxwriter` cannot read.

Run them with:

```
odoo-bin -d <db> -i jito_timesheet_rounding --test-enable \
         --test-tags /jito_timesheet_rounding --stop-after-init
```

# jito_timesheet_rounding — Developer Guidance

## What this module does

**Automatic hours tracking rounding** — a per-company setting that snaps Hours
Spent (`account.analytic.line.unit_amount`) onto a 15- or 30-minute grid when a
timesheet is saved. Nothing is rejected; the employee never has to correct a
number by hand.

That is the whole module. It touches nothing outside `unit_amount`: not the
exports, not `tm_adjusted_hours`, not any other model.

> **History:** 3.2.0 also shipped an XLSX export override that wrote
> `tm_adjusted_hours` with the Excel `[h]:mm` number format, so off-grid values
> read as `01:10` rather than `1.17`. It was dropped in 3.3.0: with tracked hours
> on a 15/30-minute grid, every duration is a clean multiple of a quarter hour and
> a decimal export column is unambiguous on its own. Exports are back to stock
> Odoo behaviour — do not reintroduce the override without that decision being
> revisited.

---

## The rounding rule

`models/rounding.py::round_to_grid(hours, step_minutes)` is the whole rule, in
one pure function:

| input | on a 15-minute step | why |
|---|---|---|
| no step configured | unchanged | rounding is off |
| exactly `0` | `0` | an empty duration is a legitimate entry, not 15 minutes of work nobody did |
| already on the grid | **the identical object** | rebuilding it would replace a stored `1.25` with a value that is equal but not identical, and every such write is a pointless UPDATE |
| 1:07 / 1:08 | 1:00 / 1:15 | nearest multiple |
| 1:07:30 | 1:15 | ties away from zero |
| 0:05 | 0:15 | magnitude is floored at one step |
| −0:20 | −0:15 | sign preserved, magnitude rules applied to `abs()` |

Two details that look like nitpicks and are not:

- **Ties use `floor(steps + 0.5)`, not `round()`.** The builtin rounds half to
  *even*, so `round(4.5) == 4` but `round(5.5) == 6`. On a 15-minute grid that
  sends 1:07:30 down to 1:00 while 1:37:30 goes up to 1:45 — the same half-step
  landing on either side depending on where it falls.
- **Never below one step.** Rounding 5 minutes down to nothing loses work that
  was genuinely logged and leaves a 0:00 row that reads as a mistake.

---

## Stored history is never rewritten

Rounding happens **on save, and only on save**. There is no sweep over stored
rows, no recompute, no bulk tool — and there must not be one. What that
guarantees, concretely:

- enabling the setting changes no stored value;
- a legacy off-grid entry keeps its duration until someone edits *that duration*.
  Renaming it, moving it to another task, or rewriting the same value back all
  leave the number alone (`write()` compares old and new before rounding);
- when a user does change the duration, the new value is snapped onto the grid —
  legacy entry or not. Whatever is typed today lands on today's grid.

> **History:** 2.x *rejected* off-grid durations, so it needed a cut-off —
> `res_company.timesheet_rounding_start_date` — to keep the ~3 775 pre-existing
> off-grid entries editable rather than frozen. 3.0.0 rounds instead of
> rejecting, so nothing is ever blocked and the cut-off protects nothing. The
> field, `_is_new_for_rounding()`, the stamping overrides on `res.company` and
> the 2.0.0 migration are all gone; `migrations/17.0.3.0.0/post-migrate.py` drops
> the orphan column. Do not reintroduce the concept without revisiting that.

---

## What is deliberately out of scope

| | rounded? | why not |
|---|---|---|
| Hours Spent (`unit_amount`) on a timesheet | **yes** | the feature |
| Analytic lines with no `project_id` | no | invoicing and accounting store a *quantity* here, not a duration. Snapping those onto an hours grid corrupts accounting figures |
| Leave-generated timesheets (`holiday_id` / `global_leave_id`) | no | `project_timesheet_holidays` writes `unit_amount` from the working schedule and keeps it equal to the leave duration. A 7.6 h day rounded to 7.5 h leaves the timesheet disagreeing with its leave. *(2.x had this wrong: such a line was **rejected**, which could block a leave approval.)* |
| Adjusted Hours (`tm_adjusted_hours`) | no | a billing correction, not tracked time — a PM legitimately enters 1:10 there |

`project_timesheet_holidays` is **not** a dependency, so its two fields may not
exist. `_is_leave_timesheet()` looks them up in `_fields` rather than accessing
them directly; keep it that way.

---

## Main models and where things live

### `res.company`
`timesheet_rounding_enabled` (Boolean), `timesheet_rounding_step` (`15` / `30`),
and `_timesheet_rounding_minutes()` — the step in minutes, or `0` when disabled.
Every other component asks that method rather than reading the fields.

### `res.config.settings`
Related fields plus `set_values()`, which aligns the timer with the step — see
"Timer" below.

### `account.analytic.line`
- `_is_leave_timesheet()` — the `project_timesheet_holidays` guard
- `_timesheet_rounding_step()` — step for this line, `0` when out of scope
- `_round_timesheet_duration()` — corrects already-created lines
- `create()` rounds **after** `super()`; `write()` rounds **before** it
- `_onchange_unit_amount_round_to_step()` — the form/list preview

### `ir.http`
`session_info()` publishes `timesheet_rounding_step` so the grid patch knows
whether it has anything to do. Internal users only.

### `static/src/grid_cell_rounding.js`
Patches `GridCell._update` so a grid cell shows the stored value rather than the
typed one — see "Grid view cells" below.

### `models/rounding.py`
Pure helpers (`round_to_grid`, `is_on_grid`, `steps_in`, `format_duration`) with
no ORM access, so they are unit-testable and shared by the models.

---

## Patterns and constraints worth knowing

### Why `create()` and `write()` round on opposite sides of `super()`

This asymmetry is intentional; do not "fix" it.

- **`write()` rounds the incoming `vals` before `super()`.** The records already
  exist, so `project_id`, `company_id` and the leave links can be read straight
  off them. Nothing downstream ever observes the un-rounded number and there is
  no second UPDATE.
- **`create()` cannot.** At that point `project_id` may still be absent from
  `vals` (it is computed from `task_id`) and so may `company_id` (`hr_timesheet`
  fills it from the employee, `hr_timesheet.py::create`). Both decide whether and
  how the line is rounded. Resolving them in this module would mean duplicating
  core's own resolution — and re-duplicating it every time core changes it. So
  the line is inserted first and corrected after, when the real values are on the
  record. The correction carries the skip flag, so it cannot recurse.

### Why `write()` groups by step
`vals` carries one `unit_amount` for the whole recordset, but the step is a
company setting and some lines may be out of scope entirely. Lines are grouped by
the step that applies to them and each group gets its own write. The common
single-group case still issues a single UPDATE.

### Why not `@api.constrains`
A constraint has no access to the previous value, and an unrelated edit on an
off-grid legacy entry must not touch its duration — `write()` needs the old and
new values side by side.

### The onchange is feedback, not enforcement
`_onchange_unit_amount_round_to_step()` changes no stored value. `create()` and
`write()` already round on the way to the database; the onchange only moves the
same correction forward to where the person can still see it happen. Without it
the field keeps showing the number that was typed until the record is reloaded,
which reads as "the setting is not working".

It cannot be the *only* mechanism — an onchange never fires for imports, the API,
or `grid_update_cell` — so the two layers are deliberate, and
`test_it_agrees_with_what_would_have_been_stored` pins them to the same answer.
If you change `round_to_grid`, that test is what catches a preview that lies.

The warning goes back as a **notification**, not a dialog. Odoo's web client
renders an onchange warning as a toast unless `type` is `'dialog'`
(`web/static/src/model/relational_model/relational_model.js::_onchange`, which
destructures `{type, title, message, className, sticky}` and only builds a
`WarningDialog` for `"dialog"`). Nothing went wrong and nothing needs
acknowledging, so a modal would be the wrong weight.

Messages use `format_duration()` to speak in `h:mm`. Telling someone their
"1.37 became 1.25" would be worse than saying nothing — they typed 1:22.

### Grid view cells
The grid does not go through onchange, and it has its own display bug to work
around. `GridCell._update` (`web_grid/static/src/views/grid_model.js`) calls
`grid_update_cell` on the server and then does
`this.row.updateCell(this.column, value)` — with the value it just *sent*, not
the one the server kept. So a rounded cell went on showing the typed number until
the grid was reloaded. The stored value was right all along; only the display
lagged, which reads as "the setting is not working".

`static/src/grid_cell_rounding.js` patches `_update` to re-read the cell after
the write and correct it in place. Three things about it are load-bearing:

- **It asks the server instead of rounding in the browser.** A cell is the *sum*
  of the lines under it, while `grid_update_cell` applies the difference to a
  single line. With two lines in one cell — an approved entry beside a new one —
  rounding the total is not the same arithmetic as rounding the line the server
  actually touched, and a client-side guess would drift from the stored figure.
- **It costs nothing when the feature is off.** `ir_http.py::session_info`
  publishes `timesheet_rounding_step`; a `0` there and the patch returns before
  spending an RPC. The read itself is one `read_group` scoped to the single cell,
  not a grid reload.
- **It re-uses `row.updateCell`**, which works in deltas, so the row, column and
  section totals that were summed from the typed value are corrected too.

It bails out when the server answered with an action (`this.value !== value` —
no project on the row, timesheets disabled) and when nothing changed
(`value === previousValue`, where `grid_update_cell` returns early). A failed
re-read is swallowed: a cosmetic correction must never break an edit that
succeeded.

`patch()` supports `super` because it sets the previous implementation as the
extension's prototype (`web/static/src/core/utils/patch.js:112`).

### Escape hatch
`with_context(skip_timesheet_rounding_check=True)` bypasses rounding entirely,
for automated flows that own the duration (data fixes, historical imports). Never
set it from the UI. The key name is unchanged from 2.x.

### Timer
`timesheet_grid` rounds every timer stop **up** to
`timesheet_grid.timesheet_rounding` minutes, with `timesheet_min_duration` as a
floor (`timer/models/timer_mixin.py::_timer_rounding`). Both are **global system
parameters**, not per-company ones, and they are read from six different places
in `timesheet_grid`.

Rather than override all six, `set_values()` writes the company step into both
parameters when rounding is enabled. Otherwise the timer would produce, say,
15-minute entries while the company step is 30 — and every one of them would then
be rounded again on save, so the duration the user watched the timer reach is not
the one that gets stored.

> **Limitation:** those parameters are global. With several companies on
> different steps, the last saved one wins for the timer. When rounding is
> disabled the parameters are left untouched.

### Exports are stock — deliberately (3.3.0)
This module registers **no controller**. `Action → Export → .xlsx` goes straight
to core, so every float column lands with the standard `#,##0.00` format,
including Hours Spent and Adjusted Hours.

3.2.0 shipped an override of `/web/export/xlsx` that wrote `tm_adjusted_hours`
with the Excel `[h]:mm` format. It existed for one reason: to make off-grid
durations such as 1:10 (stored `1.1666…`, exported `1.17`) readable in a
spreadsheet. Once tracked hours are snapped onto a 15/30-minute grid, every
duration is a whole number of quarter hours, `1.25` is unambiguous in a decimal
column, and the override earned nothing to offset its cost: an export controller
override runs for **every model's** xlsx export, and it put durations in day
fractions next to decimal hours, so a cross-column formula compared different
units.

Two things follow from having dropped it:

- the `tm_rate_card` dependency is gone from the manifest — nothing here reads
  `tm_adjusted_hours` any more;
- controllers register at server start, so removing this one needs a **restart**,
  not just a module upgrade.

Adjusted Hours still reads as `h:mm` *in the web client*: `tm_rate_card`'s tree
view declares `widget="float_time"` on the field, which was never part of this
module.

---

## Tests

| file | covers |
|---|---|
| `test_rounding_apply.py` | `round_to_grid` itself (nearest, ties up, one-step floor, zero, no step, on-grid identity, negatives); rounding on create incl. batch create; rounding on write incl. legacy entries, unrelated edits and same-value writes; the onchange preview, its notification type and its `h:mm` wording, and that it agrees with what create would store; scope guards (no project, leave timesheets, skip context, per company) |
| `test_session_step.py` | the step reaches the browser through `/web/session/get_session_info`, is `0` when rounding is off, and the key is always present |

`session_info()` cannot be called from a `TransactionCase` — core reads
`request.session.uid` and raises `RuntimeError: object is not bound` without a
real request (`web/models/ir_http.py`) — hence the `HttpCase`. Pass `{}` as
params, never `None`: the JSON dispatcher does
`dict(self.jsonrequest.get('params', {}), **args)`.

⚠️ **The grid patch itself has no automated test.** There is no browser in this
environment (`browser_js` needs Chrome), so `grid_cell_rounding.js` is covered
only indirectly: `TestGridCellRounding` pins the two server-side facts it stands
on — `grid_update_cell` stores a rounded value, and a `read_group` over the cell
returns that rounded figure. If you change the patch, check it in a real browser.

`tests/common.py` works in **minutes** and converts, so expectations read the way
the rule is stated ("68 minutes becomes 75") instead of as decimal hours nobody
can check at a glance. `assertMinutes()` compares that way too.

The leave-timesheet test skips itself when `project_timesheet_holidays` is not
installed, since it is not a dependency.

Run them with:

```
odoo-bin -d <db> -u jito_timesheet_rounding --test-enable \
         --test-tags /jito_timesheet_rounding --stop-after-init
```

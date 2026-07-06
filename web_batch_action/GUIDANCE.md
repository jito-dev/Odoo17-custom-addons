# web_batch_action — Batch Action Processing

## What this module does
Adds a **"Batch"** checkbox + a **records-per-batch** number input (default **100**) right next to the **Actions**
button in any list view's selection bar. When **Batch is ticked**, running a **Server Action** on a selection of N
records processes it **client-side in sequential slices** of the configured size — e.g. 10 000 records with a batch
size of 100 = **100 runs of 100 records** — instead of one RPC with all `active_ids` (which times out / hits
`active_ids_limit` / gives no progress).

It is **frontend-only** (no models, no schema). It patches the standard web `ActionMenus` component, so it works on
**every** list view automatically, for any custom Server Action — no per-model code.

## Pipeline mode (ordered multi-action chain)
Beyond running **one** action, you can compose an **ordered pipeline** of several Server Actions and run the whole
chain over one selection in a single click — no manual re-selection between steps.

- **Compose & order:** each Server Action in the ⚙ **Actions** menu now has a **checkbox** on its left. Tick one → it
  becomes step **①**, tick another → **②**, etc. (the number shows to the left). Untick → the number disappears and
  the rest **renumber** automatically. Ticking a box neither runs the action nor closes the menu.
- **Run:** a **Run pipeline (N)** button appears next to *Batch* once ≥1 action is ticked. It resolves the selection
  once, shows a **confirmation** (steps × records × batches + mode), then runs the chain. A normal single click on an
  action still runs just that one (unchanged).
- **Loop-nesting toggle** — a **"Batch of sequences"** checkbox next to the size input (default **off**):
  - **Off — sequence of batches** (action-major): `for each action → for each batch`. Step ① clears the *whole*
    selection before ② starts.
  - **On — batch of sequences** (record-major): `for each batch → for each action`. Each batch is driven through
    ①②③ before the next batch.
- **Failure rule:** **abort the chain for the affected batch only.** If a step fails on batch *b*, the remaining
  steps for *b* are **skipped** (not run on a known-bad state); other batches/steps proceed. Genuine failures are
  retried via the same cooldown/retry rounds; **skipped** cells stay skipped (re-run the pipeline if you need them).
- **Persistence:** the configured order is **session-only** — it resets on reload/navigation. (The *Batch* on/off +
  size still persist in `localStorage` as before.) Only **Server Actions** are chainable (Archive/Delete/Export/Print
  get no checkbox).
- **Progress:** the dialog shows a per-step roll-up (ok / failed / skipped), a "Step S/N — batch X/Y" status line,
  and a **Step** column in the failures table. Implemented in `onRunPipeline` + `_runPipeline*` in
  `action_menus_batch.js`; the grid is a `steps[].batches[]` reactive shared with the dialog.

## How it works
- **Single interception point:** `ActionMenus.executeAction(action)` (Odoo core
  `web/static/src/search/action_menus/action_menus.js`) is the only place a Server Action is launched from the
  Action menu. We `patch` it: when Batch is off we call `super.executeAction` (unchanged); when on, we run the
  batch loop.
- **ID resolution:** an explicit selection uses the selected resIds (`props.getActiveIds()`); a *"select all
  matching domain"* selection is resolved by **paginating `orm.search`** (page 10 000) so batching can cover the
  whole set beyond the single-call `active_ids_limit`, bounded by a `MAX_IDS` safety cap (200 000) that aborts with
  a notification rather than running away.
- **Execution:** the ids are sliced into chunks; each chunk is run **sequentially** via
  `rpc("/web/action/run", {action_id, context})` with `context.active_ids` = the slice. We call `/web/action/run`
  **directly instead of `action.doAction`** so the per-batch *returned* follow-up action (act_window / report /
  notification) is **discarded** — otherwise a 100-batch run would open 100 dialogs/downloads. One consolidated
  summary is shown instead.
- **Progress UI:** a `BatchProgressDialog` (OWL `Dialog`) subscribes to a shared `reactive` progress object the
  loop mutates — live bar, "batch X of N", succeeded/failed counts, and a failures table. `header=false` so it
  can't be silently dismissed; the footer shows **Cancel** while running and **Close** when done.

## Files
| File | Role |
|---|---|
| `static/src/action_menus_batch.js` | **Core.** `patch(ActionMenus)`: batch state (+ `localStorage` prefs), `executeAction` override, id pagination, the sequential batch loop, `beforeunload` guard, summary notification. |
| `static/src/action_menus_batch.xml` | `t-inherit="web.ActionMenus"` — injects the Batch checkbox + size input (with a `data-tooltip`) inside `div.o_cp_action_menus`. |
| `static/src/batch_progress_dialog.js` / `.xml` | The progress/cancel/summary modal. |
| `static/src/batch_action.scss` | Minor sizing for the inline input and failures table. |
| `__manifest__.py` | `depends: ['web']`; assets in `web.assets_backend`. |

## Timing metrics (progress dialog)
The dialog shows live timing derived from a 1 s reactive ticker (`progress.nowTs`) and per-batch durations:
- **Time spent** (elapsed; becomes **Total time** when done), **Last batch** time, **Average** batch time, and
  **Throughput** (records/sec over elapsed).
- While running, an **ETA** line: an absolute end time formatted like `Sun Jun 14 22:47:02` (plain `Date`, no
  dependency) plus a relative **(~Xm Ys left)**.
- The ETA reflects the **current trajectory** — the in-progress pass plus an imminent cooldown; it does **not**
  predict how many *future* retry rounds will be needed (unknowable). Timings are recorded in
  `action_menus_batch.js` (`_runOneBatch` / the ticker in `_runBatches`); all formatting lives in
  `batch_progress_dialog.js` (`fmtDur` / `fmtMs` + getters). The summary toast appends the total elapsed seconds.

## Retry rounds (failed batches)
After the **initial pass** over all batches, any batches that **failed** are retried in **rounds**:
- Wait a **60 s cooldown** (`COOLDOWN_SECONDS`), shown as a live countdown in the dialog, then re-run **only the
  still-failing batches** (the whole chunk). Repeat for up to **3 rounds** (`MAX_RETRIES`) — a batch is attempted at
  most 4× (1 initial + 3 retries).
- The loop stops early as soon as **no batches are failing**. If nothing failed, there is **no** cooldown/retry.
- During a cooldown the dialog offers **Retry now** (skip the remaining wait and retry immediately) and **Cancel**.
- The `beforeunload` "Leave site?" guard stays armed **through cooldowns** until the whole process finishes.
- Batches still failing after the last round are listed in the summary with their **attempt count** and last error,
  plus a sticky warning toast.
- **Caveat:** *all* failures are retried (no transient-vs-permanent heuristic) — a deterministic error simply
  re-fails each round and is reported at the end. Constants `COOLDOWN_SECONDS` / `MAX_RETRIES` live at the top of
  `static/src/action_menus_batch.js`.

State is tracked per batch (`{no, chunk, count, status, attempts, error}`) in the shared `reactive` object; the
progress dialog derives all counts from it, so the bar, round indicator and failures table update live.

## Failure handling & semantics (important)
- **Continue-on-error:** a failing batch is recorded (batch #, count, error) and the loop **continues**; the summary
  lists all failures. Never aborts the whole run on one error.
- **Per-batch isolation:** each `/web/action/run` is its own request/transaction → a failure in batch 7 does **not**
  roll back batches 1–6. Successes are committed and kept.
- **Cancel:** the Cancel button sets a flag checked between batches; the in-flight batch finishes, the rest are
  skipped, and the dialog shows a partial summary.
- **Closing the tab mid-run:** a `beforeunload` listener triggers the browser's native "Leave site?" prompt while a
  run is active. If the user leaves anyway: the in-flight batch may still commit server-side, **already-finished
  batches stay saved**, and the **unsent batches simply don't run** (the loop lives only in that tab). Re-running on
  the remaining records is safe for per-record actions. The checkbox tooltip states this.
- **Suppressed follow-up actions:** returned act_window/report/notification per batch are intentionally discarded.
  **Limitation:** batch mode is for **per-record bulk mutations**, not for Server Actions whose returned
  wizard/window is the point, nor for actions that *aggregate across* `active_ids` (e.g. "merge these"), which
  batching would change the meaning of.
- **Scope:** only Server Actions (the `executeAction` path). Archive/Unarchive/Delete/Export/Print use other code
  paths and are unaffected by the toggle.
- **Input validation:** batch size is coerced to an integer ≥ 1; the choice (enabled + size) is remembered in
  `localStorage` (`web_batch_action.enabled` / `.size`).

## Install / upgrade
Frontend-only → no DB schema. Install/upgrade with `-i`/`-u web_batch_action`; the change is an assets reload.

## Manual verification
1. Create a throwaway Server Action on `res.partner` bound to the list view (`binding_view_types=list`, `state=code`,
   e.g. `for r in records: r.comment = 'touched'`). Open Contacts.
2. Tick **Batch**, set size **10**, run → progress dialog shows batches; Network tab shows multiple
   `/web/action/run` calls; all selected records updated; one reload + success toast.
3. **Select all** on a big filtered set → paginated ids, sliced beyond one page.
4. Server action that raises for some ids → run continues, summary lists failed batches, successes kept.
5. **Cancel** mid-run → stops after current batch, partial summary.
6. Start a run, try to reload/close the tab → native "Leave site?" prompt; gone after completion.
7. Untick **Batch** → action runs exactly as before (single call, normal returned-action handling).

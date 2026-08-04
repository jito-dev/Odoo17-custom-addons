# -*- coding: utf-8 -*-
"""Repair billing run totals left stale by the July backfill in `post-migrate.py`.

Two separate reasons this cannot live in the post-migrate script:

1. **`modified()` does not reach these fields.** The dependency chain is
   `account.analytic.line.tm_adjusted_hours` -> `tm.billing.run.line.timesheet.hours`
   (a *non-stored related* field) -> `tm.billing.run.line.hours` (stored compute). The
   trigger does not propagate backwards across the non-stored related hop, so the run
   line keeps the total computed from the truncated hours. Reproduced on a production
   copy: a draft run stayed at 0.17 after its timesheet was restored to 0.1666...

2. **`tm.billing.run.line` does not exist in the registry during post-migrate.** Those
   models belong to `tm_billing_control`, which *depends on* `tm_rate_card` and is
   therefore loaded later in the module graph. `end-` scripts run after every module has
   been loaded (`odoo/modules/loading.py:519`), which is the first point where the model
   is addressable. Version gating still works there because `load_version` is captured
   before the module state is updated (`loading.py:301`).

Recomputing is idempotent - it only re-derives stored aggregates from the current
timesheet values - so this is safe to run over the whole window rather than tracking the
exact ids the backfill touched.

Runs in state `invoiced`/`closed` are excluded, matching the skip guard in post-migrate:
their timesheets were never backfilled, so their totals must not move either.
"""

import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

# Must match the window in post-migrate.py.
DATE_FROM = '2026-07-01'
DATE_TO = '2026-08-01'

AFFECTED_LINES = """
    SELECT DISTINCT rl.id
      FROM tm_billing_run_line rl
      JOIN tm_billing_run_line_timesheet t ON t.billing_line_id = rl.id
      JOIN account_analytic_line l ON l.id = t.timesheet_id
      JOIN tm_billing_run r ON r.id = rl.billing_run_id
     WHERE l.date >= %s AND l.date < %s
       AND r.state NOT IN ('invoiced', 'closed')
"""


def migrate(cr, version):
    if not version:
        return

    env = api.Environment(cr, SUPERUSER_ID, {})
    if 'tm.billing.run.line' not in env:
        _logger.info("tm_rate_card 1.14.9: tm_billing_control not installed, no run totals to repair")
        return

    cr.execute(AFFECTED_LINES, (DATE_FROM, DATE_TO))
    line_ids = [row[0] for row in cr.fetchall()]
    if not line_ids:
        _logger.info("tm_rate_card 1.14.9: no open billing run lines in %s..%s", DATE_FROM, DATE_TO)
        return

    Line = env['tm.billing.run.line']
    lines = Line.browse(line_ids)
    env.invalidate_all()
    for fname in ('hours', 'amount'):
        env.add_to_compute(Line._fields[fname], lines)
    env.flush_all()

    # The run header does NOT cascade from the line writes above, even though
    # `_compute_stats` declares `@api.depends('line_ids.hours', ...)`: the recompute
    # queued here is flushed after the header has already been processed in this same
    # flush cycle, so the trigger lands too late and the header keeps the old total.
    # Verified - without this second pass a draft run stayed at 0.17 while its only line
    # had already been corrected to 0.1666... Queue the header fields explicitly.
    Run = env['tm.billing.run']
    runs = lines.mapped('billing_run_id')
    for fname in ('line_count', 'total_hours', 'total_amount', 'timesheet_count'):
        env.add_to_compute(Run._fields[fname], runs)
    env.flush_all()

    _logger.info(
        "tm_rate_card 1.14.9: recomputed totals on %s open billing run line(s) "
        "across %s run(s)", len(line_ids), len(runs)
    )

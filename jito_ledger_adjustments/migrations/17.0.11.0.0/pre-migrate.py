# -*- coding: utf-8 -*-

"""Pre-migrate to 17.0.11.0.0 — remove the Bridging feature.

The ``jito.mgt.bridging`` model (two-stage bridge → clearance) is deleted;
Restatement + Regrouping (now partial-capable) cover the flows. Odoo's
module-update orphan cleanup drops the removed model's table + records on
its own; this drops the table (and its source-line M2M relation) defensively
so nothing lingers. The ``mgt_bridge`` entry_type and the trace 'bridges' /
'clears' kinds are KEPT as inert Selection values for existing-data safety.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("DROP TABLE IF EXISTS jito_mgt_bridging_source_line_rel CASCADE")
    cr.execute("DROP TABLE IF EXISTS jito_mgt_bridging CASCADE")
    _logger.info(
        "jito_ledger_adjustments 17.0.11.0.0: dropped jito_mgt_bridging."
    )

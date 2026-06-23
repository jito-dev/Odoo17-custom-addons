# -*- coding: utf-8 -*-

"""Post-migration for 17.0.2.4.0.

Initializes the two new dashboard-config fields on existing
`jito.ledger.journal` rows:

  * `show_on_dashboard` defaults to TRUE so previously-configured
    journals appear on the new dashboard out of the box.
  * `color` defaults to 0 (no color).

New rows pick the defaults up from the field declarations; this
migration only matters when Odoo's schema sync adds the columns as
NULL on existing rows.

Idempotent — only touches rows where the field is currently NULL.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("""
        UPDATE jito_ledger_journal
           SET show_on_dashboard = TRUE
         WHERE show_on_dashboard IS NULL
    """)
    show_count = cr.rowcount
    cr.execute("""
        UPDATE jito_ledger_journal
           SET color = 0
         WHERE color IS NULL
    """)
    color_count = cr.rowcount
    _logger.info(
        "jito_ledger_core 17.0.2.4.0: initialized show_on_dashboard "
        "on %d journal(s) and color on %d journal(s).",
        show_count, color_count,
    )

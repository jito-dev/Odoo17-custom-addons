# Copyright © 2026 Garazd Creation (<https://garazd.biz>)
# License OPL-1 (https://www.odoo.com/documentation/17.0/legal/licenses.html).
"""Enable candidate auto-sync on every existing Djinni-linked vacancy.

Recruiters asked for candidates to be pulled automatically for all vacancies
(the candidate listing is free of Djinni data-extraction credits). Auto-sync
used to be opt-in and OFF by default, so this one-time migration flips the
existing vacancies ON at the 30-minute interval. The field default stays OFF,
so vacancies created *after* this rollout are still opt-in.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute(
        """
        UPDATE hr_job
           SET djinni_auto_sync_candidates = TRUE,
               djinni_sync_interval = 'every_30min'
         WHERE djinni_ref IS NOT NULL
        """
    )
    _logger.info(
        "hr_djinni: enabled candidate auto-sync (every_30min) on %s Djinni vacancies.",
        cr.rowcount,
    )

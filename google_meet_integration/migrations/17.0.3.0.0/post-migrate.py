# -*- coding: utf-8 -*-
"""Post-migrate → 17.0.3.0.0.

On a FRESH install the ``post_init_hook`` flips existing Appointment Types from
Odoo Discuss to Google Meet. But on an UPGRADE of an already-installed module
(the production case) ``post_init_hook`` does NOT run — only migrations do. Since
v17.0.3.0.0 also HIDES the "Videoconference Link" selector, an existing
``discuss`` type would otherwise be stuck on Discuss with no UI to change it.
This migration performs the same idempotent flip on upgrade.

Conservative (mirrors ``hooks.post_init_hook``):
  * only rows on ``discuss`` are changed;
  * rows left empty/False ("no video link") are NEVER touched;
  * idempotent — re-running finds nothing left on 'discuss'.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("""
        UPDATE appointment_type
           SET event_videocall_source = 'google_meet'
         WHERE event_videocall_source = 'discuss'
        RETURNING id
    """)
    flipped = [r[0] for r in cr.fetchall()]
    _logger.info(
        "google_meet_integration 17.0.3.0.0: switched %d Appointment Type(s) "
        "from Odoo Discuss to Google Meet on upgrade (ids=%s).",
        len(flipped), flipped)

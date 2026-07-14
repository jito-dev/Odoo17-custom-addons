# -*- coding: utf-8 -*-
import logging

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    """Flip every existing Appointment Type still on Odoo Discuss to Google
    Meet, so the system is consistent the moment this module installs (new
    types already default to google_meet via the field override).

    Conservative on purpose:
      * only rows with ``event_videocall_source = 'discuss'`` are changed;
      * rows left empty/False ("no video link") are NEVER touched — an
        intentionally link-less type stays link-less;
      * idempotent — re-running finds nothing left on 'discuss'.
    """
    types = env['appointment.type'].with_context(active_test=False).search(
        [('event_videocall_source', '=', 'discuss')])
    if not types:
        _logger.info(
            "google_meet_integration: no Appointment Type on 'discuss'; "
            "nothing to convert.")
        return
    types.write({'event_videocall_source': 'google_meet'})
    _logger.info(
        "google_meet_integration: switched %d Appointment Type(s) from Odoo "
        "Discuss to Google Meet (ids=%s).", len(types), types.ids)

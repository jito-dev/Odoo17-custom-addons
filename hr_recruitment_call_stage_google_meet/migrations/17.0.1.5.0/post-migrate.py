# -*- coding: utf-8 -*-
"""Revert Call Stage booking types from the REST mint back to the native flow.

``google_meet_integration``'s up-front REST mint (source ``'google_meet_rest'``)
needs the Google Meet API OAuth scope (``meetings.space.created``). Connected
accounts authorised before that scope existed do not have it, so the mint 403s
and booked calls silently get no Meet link. Worse, selecting ``'google_meet_rest'``
makes ``appointment_google_calendar`` strip ``conferenceData`` on sync, disabling
the native Meet creation that *was* working.

This flips every Call Stage booking appointment type back to the native
``'google_meet'`` source, so Odoo's Google Calendar sync attaches a Meet
conference again — the same link Google creates for a manual calendar event.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    configs = env['hr.job.stage.config'].search([
        ('is_call_stage', '=', True),
        ('booking_appointment_type_id', '!=', False),
    ])
    if not configs:
        return
    stale = configs.booking_appointment_type_id.filtered(
        lambda at: at.event_videocall_source != 'google_meet'
    )
    if stale:
        _logger.info(
            "Reverting %s call-stage booking appointment type(s) to native "
            "'google_meet': %s",
            len(stale), stale.mapped('name'),
        )
    configs._apply_call_stage_google_meet_source()

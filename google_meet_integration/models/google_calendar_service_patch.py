"""Extends Odoo's Google Calendar OAuth scope to include Google Meet.

The enterprise ``google_calendar`` module builds its consent URL from
``GoogleCalendarService._get_calendar_scope`` (single call site at
``google_calendar/utils/google_calendar.py:134``). Appending the Meet scope
here means every new Google connection consented to through Odoo will also
authorize Meet space creation, reusing the same refresh token.

Existing connections made before this module was installed will not gain
Meet scope silently; they'll hit a 403 on the first mint and are prompted
to re-consent — handled in ``google_meet_service._mint_meet_space``.
"""
from odoo.addons.google_calendar.utils.google_calendar import GoogleCalendarService

MEET_SCOPE = 'https://www.googleapis.com/auth/meetings.space.created'

_original_get_calendar_scope = GoogleCalendarService._get_calendar_scope


def _get_calendar_scope_with_meet(self, RO=False):
    base = _original_get_calendar_scope(self, RO=RO)
    if MEET_SCOPE in base:
        return base
    return f"{base} {MEET_SCOPE}"


GoogleCalendarService._get_calendar_scope = _get_calendar_scope_with_meet

# -*- coding: utf-8 -*-
"""Resilience hardening for the native Google Calendar two-way sync.

Fixes a stock Odoo "poison-pill" crash: in
``google_calendar/models/google_sync.py`` ``GoogleSync._sync_google2odoo`` the
``pending`` Google→Odoo loop snapshots the surviving Odoo records ONCE
(``pending_odoo = ...exists()``) before iterating. Writing one event of a
recurrence whose base-event time changed cascades and deletes *sibling* events
that are still queued later in the same loop. A later iteration then reads
``odoo_record.write_date`` on a now-deleted record → ``MissingError``. The cron
``_sync_all_google_calendar`` catches it and ``cr.rollback()``s — which also
rolls back the freshly advanced ``calendar_sync_token`` (written earlier in
``_sync_request``). The next run re-fetches the very same poison record and
crashes again: nothing imports for days ("some meetings are missing").

Diagnosed on prod 2026-06-29 (user uid=2: every cron run 06-20→06-28 raised
``MissingError (calendar.event 16906886)`` after recurrence 63694's base time
changed; self-healed only once the dead event was removed).

Fix strategy — deliberately NOT a verbatim copy of the stock method (it is long,
actively maintained across point releases, and this module has been bitten before
by forking private google_calendar internals — see the import-time monkeypatch
removed in v17.0.4.0.0). Instead we wrap ``super()`` and, on ``MissingError``
only, re-drive the sync over the Google events whose Odoo record still exists.

Why this is safe:
  * ``calendar_sync_token`` is written in ``res.users._sync_request`` BEFORE
    ``_sync_google2odoo`` runs, so letting the method complete (instead of
    raising) lets the token persist at the cron commit → the poison-loop breaks.
  * The first (failed) pass is idempotent: records it wrote carry
    ``need_sync=False`` with last-write-wins on ``write_date``, and records it
    created are reclassified as *existing* on the retry (``_event_ids_from_google_ids``
    cache is cleared on ``google_id`` writes), so nothing is duplicated.
  * We catch ``MissingError`` ONLY — never a broad ``Exception`` — so genuine
    Google updates for other records are never silently dropped.

Residual risk (documented, not papered over): a record dropped from the retry is
not re-imported under incremental sync. The recovery lever is the module's
"Sync now" forced full sync (``res.users.action_sync_google_calendar_now``).
The count of dropped events is logged at WARNING so divergence is observable.
"""
import logging

from odoo import api, models
from odoo.exceptions import MissingError

_logger = logging.getLogger(__name__)


class GoogleCalendarSync(models.AbstractModel):
    # Inheriting the ABSTRACT model applies the override to both concrete
    # models that mix it in: 'calendar.event' and 'calendar.recurrence'.
    _inherit = 'google.calendar.sync'

    @api.model
    def _sync_google2odoo(self, google_events, default_reminders=()):
        try:
            return super()._sync_google2odoo(google_events, default_reminders=default_reminders)
        except MissingError:
            # A sibling cascade (e.g. a recurrence base-time change) deleted an
            # Odoo record still queued later in the stock pending-loop. Re-drive
            # over the Google events whose Odoo record still exists; the dead
            # one(s) drop out via GoogleEvent.exists().
            survivors = google_events.exists(self.env)
            dropped = len(google_events) - len(survivors)
            _logger.warning(
                "google_meet_integration: a record was deleted mid-sync "
                "(recurrence cascade); retrying _sync_google2odoo over %s "
                "surviving Google event(s), dropped %s. Use 'Sync now' (forced "
                "full sync) to recover anything wrongly skipped.",
                len(survivors), dropped)
            # One bounded retry. A second cascade in the same batch is
            # astronomically unlikely; if it happens it re-raises to the cron's
            # existing per-user handler — no worse than stock behaviour today.
            return super()._sync_google2odoo(survivors, default_reminders=default_reminders)

    def _write_from_google(self, gevent, vals):
        # Belt-and-suspenders: if this record was unlinked by an earlier
        # sibling write in the same batch, skip rather than raise.
        if not self.exists():
            _logger.info(
                "google_meet_integration: skipping Google update for %s; the "
                "Odoo record was deleted mid-batch (recurrence cascade).", self)
            return
        return super()._write_from_google(gevent, vals)

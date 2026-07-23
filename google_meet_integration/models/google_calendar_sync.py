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

Why one retry is NOT enough (v17.0.7.1.0 — prod 2026-07-15, user uid=14):
recurrence #63742 gained an ``UNTIL`` rule, so applying it deleted 715 sibling
occurrences. The stock ``pending_odoo`` snapshot (google_sync.py:196) is taken
ONCE, before the loop, so a *single* retry can still re-hit a record deleted
during that same retry's write pass — the cascade is deterministic, not a fluke.
The previous fix wrapped only the first ``super()`` and let the retry's
``MissingError`` propagate to the cron → ``cr.rollback()`` → sync-token reverted →
identical poison next run → **infinite loop**. Cron had to be disabled by hand.

So we now retry in a BOUNDED loop and, if it still cannot converge, SWALLOW the
final ``MissingError`` and return an empty recordset. Correctness rests on two
guarantees, not on the survivor set provably shrinking (it may not — a
``GoogleEvent``'s ``_odoo_id`` is cached on the Python object and
``GoogleEvent.exists`` does not re-verify it against the DB):
  * BOUND: at most ``_MAX_G2O_RETRIES`` ``super()`` calls, then a guaranteed
    swallow — so ``MissingError`` can never reach the cron, whatever happens.
  * CONVERGENCE (best effort): each retry recomputes the stock ``pending_odoo``
    via a real recordset ``.exists()`` (google_sync.py:196) and ``continue``s
    past already-deleted records (line 199), so a retry that no longer triggers
    a *new* mid-loop deletion returns normally and imports the survivors.

Why swallowing is safe:
  * ``calendar_sync_token`` is written in ``res.users._sync_request`` BEFORE
    ``_sync_google2odoo`` runs, so returning (instead of raising) lets the token
    persist at the cron commit → the poison-loop breaks.
  * Each pass is idempotent: records it wrote carry ``need_sync=False`` with
    last-write-wins on ``write_date``, and records it created are reclassified as
    *existing* on the next pass (``_event_ids_from_google_ids`` cache is cleared
    on ``google_id`` writes), so nothing is duplicated.
  * We catch ``MissingError`` ONLY — never a broad ``Exception`` — so genuine
    Google updates for other records are never silently dropped.

Residual risk (documented, not papered over): if the loop never converges, the
affected batch is skipped and not re-imported under incremental sync. The
recovery lever is the module's "Sync now" forced full sync
(``res.users.action_sync_google_calendar_now``). Every retry and the final skip
are logged at WARNING/ERROR so divergence is observable.
"""
import logging

from odoo import api, models
from odoo.exceptions import MissingError

_logger = logging.getLogger(__name__)


class GoogleCalendarSync(models.AbstractModel):
    # Inheriting the ABSTRACT model applies the override to both concrete
    # models that mix it in: 'calendar.event' and 'calendar.recurrence'.
    _inherit = 'google.calendar.sync'

    # Hard ceiling on how many times we re-drive the stock sync after a
    # mid-batch deletion. In practice a recurrence cascade deletes all of its
    # stale occurrences in one write pass, so the first retry already sees a
    # clean pending set and converges; the ceiling only guards a pathological
    # chain. Kept small so a genuinely stuck batch is skipped promptly rather
    # than burning the cron's per-user budget.
    _MAX_G2O_RETRIES = 5

    @api.model
    def _sync_google2odoo(self, google_events, default_reminders=()):
        # A sibling cascade (e.g. a recurrence base-time change that deletes
        # hundreds of occurrences) can unlink an Odoo record still queued in the
        # stock pending-loop, raising MissingError. Re-drive in a bounded loop:
        # each pass recomputes the stock pending_odoo snapshot afresh and skips
        # already-deleted records, so a pass that no longer triggers a *new*
        # mid-loop deletion returns normally. If we exhaust the retries we
        # SWALLOW rather than raise — raising would send the cron into
        # cr.rollback(), reverting the freshly advanced calendar_sync_token and
        # re-fetching the identical poison forever (the bug we are fixing).
        events = google_events
        for attempt in range(self._MAX_G2O_RETRIES + 1):
            try:
                return super()._sync_google2odoo(events, default_reminders=default_reminders)
            except MissingError:
                # Re-derive the events whose Odoo record still resolves; the
                # dead one(s) drop out via GoogleEvent.exists() when their
                # google_id no longer maps to a live record.
                survivors = events.exists(self.env)
                dropped = len(google_events) - len(survivors)
                if attempt < self._MAX_G2O_RETRIES and survivors:
                    _logger.warning(
                        "google_meet_integration: record deleted mid-sync "
                        "(recurrence cascade); retry %s/%s over %s surviving "
                        "Google event(s), dropped %s so far.",
                        attempt + 1, self._MAX_G2O_RETRIES, len(survivors), dropped)
                    events = survivors
                    continue
                # Exhausted the budget (or nothing survives): stop the loop by
                # returning empty so the sync token persists at the cron commit.
                # MissingError ONLY — never a broad Exception. Recover any
                # skipped records via 'Sync now' (forced full sync).
                _logger.error(
                    "google_meet_integration: Google sync poison-pill did not "
                    "converge after %s retr%s; skipping the affected batch so "
                    "the sync token advances and the cron stops looping (dropped "
                    "%s event(s)). Run 'Sync now' to reimport.",
                    attempt, "y" if attempt == 1 else "ies", dropped)
                return self.browse()

    def _write_from_google(self, gevent, vals):
        # Belt-and-suspenders: if this record was unlinked by an earlier
        # sibling write in the same batch, skip rather than raise.
        if not self.exists():
            _logger.info(
                "google_meet_integration: skipping Google update for %s; the "
                "Odoo record was deleted mid-batch (recurrence cascade).", self)
            return
        return super()._write_from_google(gevent, vals)

    def _google_insert(self, google_service, values, *args, **kwargs):
        # v17.0.8.0.0 — stop the per-occurrence invitation-email storm.
        #
        # During an INCREMENTAL sync the stock code sets send_updates=True
        # (res.users._sync_google_calendar: ``send_updates = not full_sync``),
        # and _sync_odoo2google inserts every recurrence occurrence that has no
        # google_id one-by-one (google_sync.py: ``for record in new_records:
        # ..._google_insert(...)``). When a recurrence is restructured (e.g. it
        # gains an UNTIL rule, or its base time changes) its occurrences are
        # re-created as brand-new events, so a long daily meeting fans out into
        # HUNDREDS of _google_insert calls — each one telling Google
        # sendUpdates=all → one attendee-invitation email PER occurrence (~200
        # emails observed on prod 2026-07-15, user uid=14).
        #
        # The base recurrence itself is synced separately as a single
        # calendar.recurrence carrying its RRULE, so Google already notifies the
        # attendees ONCE for the series; the per-occurrence invites are pure
        # spam. We therefore force send_updates=False, but ONLY for events that
        # belong to a recurrence (self.recurrence_id). Genuine standalone new
        # meetings created in Odoo keep send_updates untouched, so their
        # legitimate invitations are still delivered.
        record = self
        if self._name == 'calendar.event' and self.recurrence_id:
            record = self.with_context(send_updates=False)
        return super(GoogleCalendarSync, record)._google_insert(
            google_service, values, *args, **kwargs)

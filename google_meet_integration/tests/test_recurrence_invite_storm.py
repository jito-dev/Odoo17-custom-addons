# -*- coding: utf-8 -*-
"""v17.0.8.0.0 — suppress the per-occurrence Google invitation-email storm.

Stock ``_sync_odoo2google`` inserts every recurrence occurrence that has no
``google_id`` one-by-one via ``_google_insert``, and during an incremental sync
``send_updates`` defaults to True, so Google emails an invitation to every
attendee for EACH occurrence. A restructured daily recurrence therefore fans out
into hundreds of invite emails.

Our ``_google_insert`` override forces ``send_updates=False`` for events that
belong to a recurrence, while leaving standalone new events untouched. These
tests pin both behaviours WITHOUT a Google round-trip: we patch the stock
``GoogleSync._google_insert`` (reached via ``super()``) and inspect the
``send_updates`` value it observes in its context.
"""
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from odoo.addons.google_calendar.models.google_sync import GoogleSync


@tagged('post_install', '-at_install')
class TestRecurrenceInviteStorm(TransactionCase):

    def _capture_send_updates(self, record, ctx):
        """Call ``record._google_insert`` (our override) with the given context
        and return the ``send_updates`` value the stock super() actually sees."""
        captured = {}

        def fake_insert(inner_self, google_service, values, *args, **kwargs):
            captured['send_updates'] = inner_self._context.get('send_updates', 'MISSING')
            return None

        with patch.object(GoogleSync, '_google_insert', fake_insert):
            record.with_context(**ctx)._google_insert(None, {})
        return captured['send_updates']

    def test_recurrence_occurrence_insert_suppresses_invites(self):
        """An occurrence that belongs to a recurrence is inserted with
        send_updates=False even when the sync context asks for True."""
        base = self.env['calendar.event'].create({
            'name': 'Daily standup',
            'start': '2026-02-02 09:00:00',
            'stop': '2026-02-02 09:15:00',
            'recurrency': True,
            'rrule_type': 'daily',
            'count': 3,
        })
        occurrences = base.recurrence_id.calendar_event_ids
        self.assertTrue(occurrences, "the recurrence expanded into occurrences")
        occurrence = occurrences[0]
        self.assertTrue(occurrence.recurrence_id)

        seen = self._capture_send_updates(occurrence, {'send_updates': True})
        self.assertIs(seen, False,
                      "per-occurrence insert must force send_updates=False")

    def test_standalone_event_insert_keeps_invites(self):
        """A genuine standalone new event (no recurrence) keeps the incoming
        send_updates so its legitimate invitation is still delivered."""
        event = self.env['calendar.event'].create({
            'name': 'One-off interview',
            'start': '2026-02-03 14:00:00',
            'stop': '2026-02-03 15:00:00',
        })
        self.assertFalse(event.recurrence_id)

        seen = self._capture_send_updates(event, {'send_updates': True})
        self.assertIs(seen, True,
                      "standalone insert must not touch send_updates")

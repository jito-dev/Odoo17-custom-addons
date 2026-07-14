# -*- coding: utf-8 -*-
"""v17.0.6.0.0 — resilience guard for the Google→Odoo sync poison-pill.

Stock ``GoogleSync._sync_google2odoo`` can raise ``MissingError`` when a record
queued in its ``pending`` loop is deleted mid-batch (a recurrence base-time
change cascading to sibling events). The cron then rolls back — including the
already-advanced sync_token — and re-fetches the same poison record forever.

These tests pin our two hardenings WITHOUT a Google round-trip:
  * ``_sync_google2odoo`` retries over the survivors on ``MissingError`` (and
    only on ``MissingError``);
  * ``_write_from_google`` is a no-op on a record already deleted in this batch.
"""
from unittest.mock import patch

from odoo.exceptions import MissingError
from odoo.tests import TransactionCase, tagged

from odoo.addons.google_calendar.models.google_sync import GoogleSync
from odoo.addons.google_calendar.utils.google_event import GoogleEvent


@tagged('post_install', '-at_install')
class TestSyncGoogle2OdooGuard(TransactionCase):

    def test_retries_over_survivors_on_missing_error(self):
        """A MissingError from the stock method triggers exactly one retry, and
        the retry is driven with the surviving Google events (dead ones dropped
        via GoogleEvent.exists)."""
        calls = []

        def fake_parent(inner_self, google_events, default_reminders=()):
            calls.append(google_events)
            if len(calls) == 1:
                raise MissingError("simulated mid-batch deletion")
            return "ok"

        batch = GoogleEvent([{'id': 'gmi-fake-1'}, {'id': 'gmi-fake-2'}])
        with patch.object(GoogleSync, '_sync_google2odoo', fake_parent):
            result = self.env['calendar.event']._sync_google2odoo(batch)

        self.assertEqual(result, "ok", "the retry's result is returned")
        self.assertEqual(len(calls), 2, "exactly one retry after MissingError")
        # The fake ids match no Odoo record, so the survivor set is empty —
        # proving the retry re-derives survivors via .exists() rather than
        # reusing the original batch verbatim.
        self.assertEqual(len(calls[1]), 0)

    def test_other_errors_are_not_swallowed(self):
        """Only MissingError is retried; any other error propagates unchanged."""
        def boom(inner_self, google_events, default_reminders=()):
            raise ValueError("not a missing error")

        with patch.object(GoogleSync, '_sync_google2odoo', boom):
            with self.assertRaises(ValueError):
                self.env['calendar.event']._sync_google2odoo(
                    GoogleEvent([{'id': 'gmi-fake-3'}]))

    def test_write_from_google_noop_on_deleted_record(self):
        """Writing a Google update onto a record deleted mid-batch must not
        raise (it is silently skipped)."""
        event = self.env['calendar.event'].create({
            'name': 'GMI guard event',
            'start': '2026-01-01 10:00:00',
            'stop': '2026-01-01 11:00:00',
        })
        event.unlink()
        # No MissingError despite the record being gone.
        self.assertIsNone(event._write_from_google(GoogleEvent([{'id': 'x'}]), {'name': 'y'}))

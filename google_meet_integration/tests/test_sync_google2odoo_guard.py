# -*- coding: utf-8 -*-
"""v17.0.7.1.0 — resilience guard for the Google→Odoo sync poison-pill.

Stock ``GoogleSync._sync_google2odoo`` can raise ``MissingError`` when a record
queued in its ``pending`` loop is deleted mid-batch (a recurrence base-time
change cascading to sibling events). The cron then rolls back — including the
already-advanced sync_token — and re-fetches the same poison record forever.

These tests pin our hardenings WITHOUT a Google round-trip:
  * ``_sync_google2odoo`` retries over the survivors on ``MissingError`` (and
    only on ``MissingError``);
  * a DETERMINISTIC cascade that raises more than once is retried in a bounded
    loop and, once the budget is exhausted, SWALLOWED (empty recordset returned)
    so the error never reaches the cron and reverts the sync token — this is the
    v17.0.7.1.0 fix over the previous single-retry;
  * ``_write_from_google`` is a no-op on a record already deleted in this batch.
"""
from unittest.mock import patch

from odoo.exceptions import MissingError
from odoo.tests import TransactionCase, tagged

from odoo.addons.google_calendar.models.google_sync import GoogleSync
from odoo.addons.google_calendar.utils.google_event import GoogleEvent


@tagged('post_install', '-at_install')
class TestSyncGoogle2OdooGuard(TransactionCase):

    def _make_synced_event(self, google_id):
        """A live calendar.event carrying a google_id, so a GoogleEvent with the
        same id resolves through GoogleEvent.exists() (survivor set stays
        non-empty across retries)."""
        return self.env['calendar.event'].create({
            'name': 'GMI guard synced event',
            'start': '2026-01-01 10:00:00',
            'stop': '2026-01-01 11:00:00',
            'google_id': google_id,
            'need_sync': False,
        })

    def test_retries_over_survivors_then_succeeds(self):
        """A single MissingError triggers a retry over the surviving Google
        events, and the retry's result is returned."""
        self._make_synced_event('gmi-real-1')
        calls = []

        def fake_parent(inner_self, google_events, default_reminders=()):
            calls.append(google_events)
            if len(calls) == 1:
                raise MissingError("simulated mid-batch deletion")
            return "ok"

        batch = GoogleEvent([{'id': 'gmi-real-1'}])
        with patch.object(GoogleSync, '_sync_google2odoo', fake_parent):
            result = self.env['calendar.event']._sync_google2odoo(batch)

        self.assertEqual(result, "ok", "the retry's result is returned")
        self.assertEqual(len(calls), 2, "exactly one retry before it converged")
        # The retry is driven with the survivor set derived via .exists(), which
        # still resolves the live event.
        self.assertEqual(len(calls[1]), 1)

    def test_deterministic_cascade_is_swallowed_not_raised(self):
        """The v17.0.7.1.0 fix: when the cascade re-raises MissingError on every
        pass (deterministic recurrence poison), the bounded loop gives up and
        SWALLOWS — returning an empty recordset instead of letting MissingError
        reach the cron (which would roll back the sync token and loop forever)."""
        self._make_synced_event('gmi-real-2')
        calls = []

        def always_missing(inner_self, google_events, default_reminders=()):
            calls.append(google_events)
            raise MissingError("deterministic recurrence cascade")

        model = self.env['calendar.event']
        batch = GoogleEvent([{'id': 'gmi-real-2'}])
        with patch.object(GoogleSync, '_sync_google2odoo', always_missing):
            # Must NOT raise — that is the whole point of the fix.
            result = model._sync_google2odoo(batch)

        self.assertEqual(result, model.browse(),
                         "an empty recordset is returned so the token persists")
        self.assertFalse(result, "result is falsy/empty")
        # Initial attempt + exactly _MAX_G2O_RETRIES retries, then swallow.
        self.assertEqual(len(calls), model._MAX_G2O_RETRIES + 1,
                         "loop is bounded by _MAX_G2O_RETRIES")

    def test_swallows_immediately_when_no_survivors(self):
        """If nothing survives the first MissingError (ids match no live record),
        the loop swallows at once rather than retrying pointlessly."""
        calls = []

        def always_missing(inner_self, google_events, default_reminders=()):
            calls.append(google_events)
            raise MissingError("simulated mid-batch deletion")

        model = self.env['calendar.event']
        batch = GoogleEvent([{'id': 'gmi-fake-1'}, {'id': 'gmi-fake-2'}])
        with patch.object(GoogleSync, '_sync_google2odoo', always_missing):
            result = model._sync_google2odoo(batch)

        self.assertEqual(result, model.browse())
        self.assertEqual(len(calls), 1,
                         "empty survivor set → swallow without retrying")

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

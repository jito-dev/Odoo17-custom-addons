# -*- coding: utf-8 -*-
"""v17.0.7.0.0 — connection observability bookkeeping.

Pins the non-network parts of the "attempt / error / failure-streak" tracking:
  * ``_record_calendar_error`` sets the reason+date and bumps the streak;
  * ``_clear_calendar_error`` and a real reconnect (``_set_auth_tokens`` with a
    refresh token) reset error + streak;
  * ``res.users._sync_google_calendar`` stamps the attempt (+success) and clears
    the streak on a clean run, and — on a raising sync — records the reason,
    bumps the streak, stamps the attempt and RE-RAISES (never swallows).

The Google round-trip is mocked; commit/rollback are neutralised so the
bookkeeping stays inside the test transaction and is assertable.
"""
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged


def _stock_sync_cls(env):
    """The google_calendar addon's ``res.users`` class that DEFINES
    ``_sync_google_calendar`` — i.e. the one our override calls via super().
    Located through the MRO instead of a hard-coded class name, because the
    class differs between editions (community ships it as ``User``)."""
    for klass in type(env['res.users']).__mro__:
        if (klass.__module__.startswith('odoo.addons.google_calendar.')
                and '_sync_google_calendar' in klass.__dict__):
            return klass
    raise RuntimeError("google_calendar _sync_google_calendar seam not found")


@tagged('post_install', '-at_install')
class TestConnectionBookkeeping(TransactionCase):

    def setUp(self):
        super().setUp()
        self.account = self.env['google.calendar.credentials'].create({})
        self.user = self.env['res.users'].create({
            'name': 'GMI Bookkeeping Tester',
            'login': 'gmi_bookkeeping@example.com',
            'email': 'gmi_bookkeeping@example.com',
            'google_calendar_account_id': self.account.id,
        })

    def test_record_error_bumps_streak(self):
        self.account._record_calendar_error("boom one")
        self.account._record_calendar_error("boom two")
        self.assertEqual(self.account.calendar_last_error, "boom two")
        self.assertTrue(self.account.calendar_last_error_date)
        self.assertEqual(self.account.calendar_consecutive_failures, 2)

    def test_clear_error_resets_streak(self):
        self.account._record_calendar_error("boom")
        self.account._clear_calendar_error()
        self.assertFalse(self.account.calendar_last_error)
        self.assertFalse(self.account.calendar_last_error_date)
        self.assertEqual(self.account.calendar_consecutive_failures, 0)

    def test_reconnect_clears_error_and_streak(self):
        """A real reconnect writes a refresh token → stale error/streak drop."""
        self.account._record_calendar_error("stale")
        self.account._set_auth_tokens('access', 'refresh', 3600)
        self.assertFalse(self.account.calendar_last_error)
        self.assertEqual(self.account.calendar_consecutive_failures, 0)

    def test_sync_success_stamps_and_clears(self):
        self.account.write({
            'calendar_last_error': 'old',
            'calendar_consecutive_failures': 3,
        })

        def fake_super(inner_self, calendar_service):
            return True

        with patch.object(_stock_sync_cls(self.env), '_sync_google_calendar', fake_super):
            self.user._sync_google_calendar(object())

        self.assertTrue(self.account.calendar_last_sync_success)
        self.assertTrue(self.account.calendar_last_sync_attempt)
        self.assertFalse(self.account.calendar_last_error)
        self.assertEqual(self.account.calendar_consecutive_failures, 0)

    def test_sync_failure_records_reason_and_reraises(self):
        self.account.calendar_consecutive_failures = 1

        def boom_super(inner_self, calendar_service):
            raise ValueError("network exploded")

        # Neutralise commit/rollback so the committed bookkeeping stays in the
        # test transaction (and the rollback does not discard our fixtures).
        #
        # And catch the exception by hand rather than with `self.assertRaises`:
        # in a TransactionCase that helper opens a savepoint and rolls it back
        # as soon as the expected exception fires (odoo/tests/common.py
        # `_assertRaises` — "Context manager that clears the environment upon
        # failure"). It would therefore discard every side effect made inside
        # the block — which here is precisely the bookkeeping under test. The
        # write reached the ORM cache and never the row, and the assertions
        # below read False.
        raised = None
        with patch.object(_stock_sync_cls(self.env), '_sync_google_calendar', boom_super), \
                patch.object(type(self.env.cr), 'commit', lambda cr: None), \
                patch.object(type(self.env.cr), 'rollback', lambda cr: None):
            try:
                self.user._sync_google_calendar(object())
            except ValueError as exc:
                raised = exc

        self.assertIsNotNone(
            raised, "a sync failure must propagate, never be swallowed")
        self.assertIn("network exploded", str(raised))
        self.assertIn("network exploded", self.account.calendar_last_error)
        self.assertTrue(self.account.calendar_last_sync_attempt)
        self.assertEqual(self.account.calendar_consecutive_failures, 2,
            "the streak advances on a sync failure, not just token failures")

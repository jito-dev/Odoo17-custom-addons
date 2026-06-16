# -*- coding: utf-8 -*-
"""v17.0.3.0.0 — on-demand "Sync now" with Google Calendar.

The actual Google round-trip cannot run in a test (no OAuth token / network),
so we pin the guard path: a user whose Google Calendar is NOT connected gets a
friendly warning notification instead of an error — the same shape the in-app
button relies on.
"""
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSyncNow(TransactionCase):
    def test_sync_now_warns_when_not_connected(self):
        user = self.env['res.users'].create({
            'name': 'Sync Tester GMI',
            'login': 'sync_tester_gmi@example.com',
            'email': 'sync_tester_gmi@example.com',
        })
        self.assertFalse(
            user.is_google_calendar_synced(),
            "precondition: the fresh user has no Google Calendar connection")

        action = user.with_user(user).action_sync_google_calendar_now()

        self.assertEqual(action['type'], 'ir.actions.client')
        self.assertEqual(action['tag'], 'display_notification')
        self.assertEqual(action['params']['type'], 'warning',
            "a not-connected user is warned, not synced or errored")

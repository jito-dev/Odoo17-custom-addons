# -*- coding: utf-8 -*-
"""v17.0.3.0.0 — on-demand "Sync now" with Google Calendar.
v17.0.5.0.0 — forced FULL sync over a focused, configurable window.

The actual Google round-trip cannot run in a test (no OAuth token / network),
so we pin the parts that do not need Google:
  * a not-connected user gets a friendly warning (the in-app guard contract);
  * the forced-full-sync window resolves to its defaults (-7d / +30d) and
    honours the ir.config_parameter overrides, clamping negatives to 0.
"""
from odoo.tests import TransactionCase, tagged

from odoo.addons.google_meet_integration.models.res_users import (
    SYNC_NOW_DEFAULT_FUTURE_DAYS,
    SYNC_NOW_DEFAULT_PAST_DAYS,
    SYNC_NOW_FUTURE_DAYS_PARAM,
    SYNC_NOW_PAST_DAYS_PARAM,
)


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

    def test_window_days_defaults(self):
        """With no override, the forced full sync reaches -7d / +30d."""
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param(SYNC_NOW_PAST_DAYS_PARAM, False)
        ICP.set_param(SYNC_NOW_FUTURE_DAYS_PARAM, False)
        self.assertEqual(
            self.env['res.users']._sync_now_window_days(),
            (SYNC_NOW_DEFAULT_PAST_DAYS, SYNC_NOW_DEFAULT_FUTURE_DAYS))

    def test_window_days_overridable_and_clamped(self):
        """System parameters override the window; negatives clamp to 0."""
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param(SYNC_NOW_PAST_DAYS_PARAM, '-3')
        ICP.set_param(SYNC_NOW_FUTURE_DAYS_PARAM, '90')
        self.assertEqual(
            self.env['res.users']._sync_now_window_days(), (0, 90))

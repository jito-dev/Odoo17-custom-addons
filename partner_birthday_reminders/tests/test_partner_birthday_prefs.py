from datetime import date, timedelta

from odoo.tests.common import tagged

from ..models.constants import (
    INTERVAL_1_DAY,
    INTERVAL_7_DAYS,
    INTERVAL_ON_DAY,
    PARAM_FALLBACK_USERS,
)
from .common import PartnerBirthdayCommon


@tagged('post_install', '-at_install')
class TestPartnerBirthdayChannels(PartnerBirthdayCommon):
    """Per-user channel switches: To Do, Discuss note, email."""

    def setUp(self):
        super().setUp()
        self.today = self._local_today()
        self.contact = self._make_contact(
            'Channel Client',
            self._same_day_birthday(self.today + timedelta(days=1)),
            user=self.manager_user,
        )
        self.pref = self.Pref._ensure_prefs_for_users(self.manager_user)

    def _run(self):
        self.env['res.partner']._cron_partner_birthday_reminders()

    def _activities(self):
        return self.env['mail.activity'].search([
            ('res_model', '=', 'res.partner'),
            ('res_id', '=', self.contact.id),
        ])

    def _mails_to_manager(self):
        """Mails addressed to this test's user only.

        The cron is global: it processes every preference row in the
        database, including those of real contacts that happen to have a
        birthday today. Asserting on the raw ``_new_mails`` therefore
        picks up other people's reminders and fails for the wrong reason.
        """
        return self._new_mails.filtered(
            lambda m: m.email_to == self.manager_user.email
        )

    def test_activity_channel_can_be_switched_off(self):
        self.pref.channel_activity = False
        self._run()
        self.assertFalse(
            self._activities(),
            "The To Do is the most-refused channel; switching it off must "
            "actually stop it.",
        )
        self.assertTrue(
            self.Log.search([('partner_id', '=', self.contact.id)]),
            "The other channels still fired, so the reminder is logged.",
        )

    def test_email_channel_can_be_switched_off(self):
        self.pref.channel_email = False
        with self.mock_mail_gateway():
            self._run()
        self.assertFalse(self._mails_to_manager())
        self.assertTrue(self._activities(), "Other channels are unaffected.")

    def test_all_channels_off_emits_nothing_and_logs_nothing(self):
        self.pref.write({
            'channel_activity': False,
            'channel_inbox': False,
            'channel_email': False,
        })
        self.assertTrue(self.pref.has_no_channel)
        with self.mock_mail_gateway():
            self._run()
        self.assertFalse(self._mails_to_manager())
        self.assertFalse(self._activities())
        self.assertFalse(
            self.Log.search([('partner_id', '=', self.contact.id)]),
            "Nothing was emitted, so nothing may be logged — a log row "
            "would permanently suppress the reminder, so re-enabling a "
            "channel later would never resend it.",
        )

    def test_reenabling_a_channel_after_silence_still_delivers(self):
        """Follows from the previous test: silence must not be recorded."""
        self.pref.write({
            'channel_activity': False,
            'channel_inbox': False,
            'channel_email': False,
        })
        self._run()
        self.pref.write({'channel_email': True, 'last_run_date': False})
        with self.mock_mail_gateway():
            self._run()
        self.assertTrue(
            self._mails_to_manager(),
            "After switching a channel back on the reminder must arrive.",
        )


@tagged('post_install', '-at_install')
class TestPartnerBirthdayWeekendShift(PartnerBirthdayCommon):
    """Weekend shift: Friday carries the weekend's deliveries."""

    def setUp(self):
        super().setUp()
        self.pref = self.Pref._ensure_prefs_for_users(self.manager_user)
        self.pref.shift_weekend_reminders = True
        self.Partner = self.env['res.partner']

    @staticmethod
    def _friday_on_or_after(day):
        return day + timedelta(days=(4 - day.weekday()) % 7)

    def test_friday_also_covers_saturday_and_sunday_deliveries(self):
        friday = self._friday_on_or_after(date(2026, 8, 3))
        targets = self.Partner._birthday_delivery_targets(
            self.pref, friday, INTERVAL_1_DAY,
        )
        self.assertEqual(
            targets,
            [friday + timedelta(days=n) for n in (1, 2, 3)],
            "On Friday the 1-day reminder must cover Saturday's, "
            "Sunday's and Monday's birthdays.",
        )

    def test_weekend_days_deliver_nothing(self):
        saturday = self._friday_on_or_after(date(2026, 8, 3)) + timedelta(days=1)
        sunday = saturday + timedelta(days=1)
        for day in (saturday, sunday):
            self.assertEqual(
                self.Partner._birthday_delivery_targets(
                    self.pref, day, INTERVAL_7_DAYS,
                ),
                [],
                "Weekend deliveries were already made on Friday.",
            )

    def test_on_day_reminder_never_shifts(self):
        saturday = self._friday_on_or_after(date(2026, 8, 3)) + timedelta(days=1)
        self.assertEqual(
            self.Partner._birthday_delivery_targets(
                self.pref, saturday, INTERVAL_ON_DAY,
            ),
            [saturday],
            "Moving 'today is their birthday' off the day would make it "
            "false, not early.",
        )

    def test_midweek_is_unaffected(self):
        wednesday = date(2026, 8, 5)
        self.assertEqual(wednesday.weekday(), 2)
        self.assertEqual(
            self.Partner._birthday_delivery_targets(
                self.pref, wednesday, INTERVAL_7_DAYS,
            ),
            [wednesday + timedelta(days=7)],
        )

    def test_shift_off_by_default_keeps_one_target(self):
        self.pref.shift_weekend_reminders = False
        friday = self._friday_on_or_after(date(2026, 8, 3))
        self.assertEqual(
            self.Partner._birthday_delivery_targets(
                self.pref, friday, INTERVAL_1_DAY,
            ),
            [friday + timedelta(days=1)],
        )


@tagged('post_install', '-at_install')
class TestPartnerBirthdayScope(PartnerBirthdayCommon):
    """Scope filter.

    Exists because one user can be the recipient for the entire contact
    base via the Default Greeters list.
    """

    def setUp(self):
        super().setUp()
        self.today = self._local_today()
        self.env['ir.config_parameter'].sudo().set_param(
            PARAM_FALLBACK_USERS, str(self.manager_user.id),
        )
        self.owned = self._make_contact(
            'Owned Client', self._same_day_birthday(self.today),
            user=self.manager_user,
        )
        self.caught = self._make_contact(
            'Caught Client', self._same_day_birthday(self.today),
        )
        self.env['res.partner']._refresh_partner_birthday_managers()
        self.pref = self.Pref._ensure_prefs_for_users(self.manager_user)

    def test_scope_all_includes_default_greeter_catch(self):
        self.pref.scope = 'all'
        self.env['res.partner']._cron_partner_birthday_reminders()
        self.assertTrue(self.Log.search([('partner_id', '=', self.caught.id)]))
        self.assertTrue(self.Log.search([('partner_id', '=', self.owned.id)]))

    def test_scope_owned_only_excludes_the_catch_all_pile(self):
        self.pref.scope = 'owned_only'
        self.env['res.partner']._cron_partner_birthday_reminders()
        self.assertTrue(
            self.Log.search([('partner_id', '=', self.owned.id)]),
            "Contacts the user actually owns must still arrive.",
        )
        self.assertFalse(
            self.Log.search([('partner_id', '=', self.caught.id)]),
            "Contacts reached only via the global Default Greeter must "
            "be excluded — the user never chose them.",
        )

    def test_scope_owned_only_counts_the_greeter_field(self):
        greeted = self._make_contact(
            'Greeted Client', self._same_day_birthday(self.today),
            birthday_greeter_id=self.manager_user.id,
        )
        self.pref.scope = 'owned_only'
        self.env['res.partner']._cron_partner_birthday_reminders()
        self.assertTrue(
            self.Log.search([('partner_id', '=', greeted.id)]),
            "Being the Birthday Greeter is ownership too, not a catch.",
        )


@tagged('post_install', '-at_install')
class TestPartnerBirthdayMyPreferences(PartnerBirthdayCommon):
    """The 'My Reminders' entry point."""

    def test_action_creates_the_row_when_missing(self):
        self.assertFalse(self.Pref.with_context(active_test=False).search([
            ('user_id', '=', self.manager_user.id),
        ]))
        action = self.Pref.with_user(self.manager_user).action_open_my_preferences()

        self.assertEqual(action['view_mode'], 'form')
        self.assertTrue(
            action['res_id'],
            "The action must open a concrete row, not a list of one.",
        )
        pref = self.Pref.browse(action['res_id'])
        self.assertEqual(pref.user_id, self.manager_user)

    def test_action_reuses_an_existing_row(self):
        existing = self.Pref._ensure_prefs_for_users(self.manager_user)
        action = self.Pref.with_user(self.manager_user).action_open_my_preferences()
        self.assertEqual(action['res_id'], existing.id)

    def test_action_finds_a_paused_row_instead_of_duplicating_it(self):
        existing = self.Pref._ensure_prefs_for_users(self.manager_user)
        existing.active = False
        action = self.Pref.with_user(self.manager_user).action_open_my_preferences()
        self.assertEqual(
            action['res_id'], existing.id,
            "A paused row is archived; searching without active_test=False "
            "would miss it and hit the UNIQUE constraint.",
        )


@tagged('post_install', '-at_install')
class TestPartnerBirthdayUpgradeDefaults(PartnerBirthdayCommon):
    """A fresh row must be inert: every channel on, no shift, full scope."""

    def test_defaults_are_conservative(self):
        pref = self.Pref._ensure_prefs_for_users(self.manager_user)
        self.assertTrue(pref.channel_activity)
        self.assertTrue(pref.channel_inbox)
        self.assertTrue(pref.channel_email)
        self.assertFalse(pref.shift_weekend_reminders)
        self.assertEqual(pref.scope, 'all')
        self.assertFalse(pref.has_no_channel)

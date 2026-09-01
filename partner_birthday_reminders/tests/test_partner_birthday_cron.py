from datetime import timedelta

from odoo.tests.common import tagged

from .common import PartnerBirthdayCommon


@tagged('post_install', '-at_install')
class TestPartnerBirthdayCron(PartnerBirthdayCommon):
    """Routing, idempotency and the interval/pause switches."""

    def setUp(self):
        super().setUp()
        self.today = self._local_today()
        # One contact per interval, all owned by manager_user.
        self.contact_today = self._make_contact(
            'Today Client', self._same_day_birthday(self.today),
            user=self.manager_user,
        )
        self.contact_tomorrow = self._make_contact(
            'Tomorrow Client',
            self._same_day_birthday(self.today + timedelta(days=1)),
            user=self.manager_user,
        )
        self.contact_week = self._make_contact(
            'Week Client',
            self._same_day_birthday(self.today + timedelta(days=7)),
            user=self.manager_user,
        )

    def _run_cron(self):
        self.env['res.partner']._cron_partner_birthday_reminders()

    def _logs(self, user=None, partner=None):
        domain = []
        if user:
            domain.append(('user_id', '=', user.id))
        if partner:
            domain.append(('partner_id', '=', partner.id))
        return self.Log.search(domain)

    # ------------------------------------------------------------------
    def test_pref_is_auto_provisioned(self):
        self.assertFalse(self.Pref.search([('user_id', '=', self.manager_user.id)]))
        self._run_cron()
        pref = self.Pref.search([('user_id', '=', self.manager_user.id)])
        self.assertEqual(len(pref), 1)
        self.assertEqual(pref.last_run_date, self.today)

    def test_all_three_intervals_fire(self):
        self._run_cron()
        intervals = set(self._logs(user=self.manager_user).mapped('interval'))
        self.assertEqual(intervals, {'on_day', '1_day', '7_days'})

    def test_activity_only_for_upcoming_intervals(self):
        self._run_cron()
        Activity = self.env['mail.activity']
        self.assertTrue(Activity.search([
            ('res_model', '=', 'res.partner'),
            ('res_id', '=', self.contact_tomorrow.id),
            ('user_id', '=', self.manager_user.id),
        ]))
        self.assertFalse(
            Activity.search([
                ('res_model', '=', 'res.partner'),
                ('res_id', '=', self.contact_today.id),
            ]),
            "The on-day interval must not create a To Do — nothing is left "
            "to prepare.",
        )

    def test_notification_is_private_to_the_account_manager(self):
        self._run_cron()
        # message_notify messages are excluded from the record's chatter.
        self.assertFalse(
            self.contact_today.message_ids.filtered(
                lambda m: m.message_type == 'user_notification'
            ),
            "Birthday notes must never surface on the customer-facing chatter.",
        )
        # Only our own notifications are inspected: assigning user_id on a
        # contact makes Odoo itself post a "You have been assigned"
        # user_notification, which follows the user's own notification_type
        # and is none of this module's business — hence the subject filter.
        birthday_messages = self.env['mail.message'].search([
            ('model', '=', 'res.partner'),
            ('res_id', 'in', (
                self.contact_today + self.contact_tomorrow + self.contact_week
            ).ids),
            ('message_type', '=', 'user_notification'),
            ('subject', 'ilike', 'birthday'),
        ])
        notification = birthday_messages.notification_ids.filtered(
            lambda n: n.res_partner_id == self.manager_user.partner_id
        )
        self.assertEqual(len(notification), 3, "One note per interval.")
        self.assertTrue(
            all(n.notification_type == 'inbox' for n in notification),
            "Inbox routing must be forced regardless of the user's "
            "notification_type preference.",
        )
        self.assertFalse(
            self.env['mail.mail'].search([
                ('mail_message_id', 'in', birthday_messages.ids),
            ]),
            "The bare message_notify email is dropped — the templated one "
            "is the single email per dispatch.",
        )

    def test_routing_is_per_account_manager(self):
        other_contact = self._make_contact(
            'Other Client', self._same_day_birthday(self.today),
            user=self.other_user,
        )
        self._run_cron()
        mine = self._logs(user=self.manager_user).mapped('partner_id')
        theirs = self._logs(user=self.other_user).mapped('partner_id')
        self.assertIn(self.contact_today, mine)
        self.assertNotIn(other_contact, mine)
        self.assertEqual(theirs, other_contact)

    def test_second_run_is_a_no_op(self):
        self._run_cron()
        before = len(self._logs())
        self.Pref.search([]).write({'last_run_date': False})  # force reprocessing
        self._run_cron()
        self.assertEqual(
            len(self._logs()), before,
            "The log's UNIQUE key must make a forced re-run emit nothing new.",
        )

    def test_same_day_rerun_is_skipped_by_last_run_date(self):
        self._run_cron()
        pref = self.Pref.search([('user_id', '=', self.manager_user.id)])
        self.assertEqual(pref.last_run_date, self.today)
        before = len(self._logs())
        self._run_cron()
        self.assertEqual(len(self._logs()), before)

    def test_disabled_interval_is_respected(self):
        pref = self.Pref.create({
            'user_id': self.manager_user.id,
            'notify_7_days_before': False,
            'notify_1_day_before': False,
            'notify_on_day': True,
        })
        self._run_cron()
        intervals = set(self._logs(user=self.manager_user).mapped('interval'))
        self.assertEqual(intervals, {'on_day'})
        self.assertEqual(pref.last_run_date, self.today)

    def test_paused_pref_receives_nothing(self):
        self.Pref.create({
            'user_id': self.manager_user.id,
            'active': False,
        })
        self._run_cron()
        self.assertFalse(self._logs(user=self.manager_user))

    def test_paused_pref_is_not_resurrected(self):
        pref = self.Pref.create({
            'user_id': self.manager_user.id,
            'active': False,
        })
        self._run_cron()
        still_paused = self.Pref.with_context(active_test=False).search([
            ('user_id', '=', self.manager_user.id),
        ])
        self.assertEqual(still_paused, pref)
        self.assertFalse(still_paused.active)

    def test_contact_without_account_manager_is_skipped(self):
        orphan = self._make_contact(
            'Orphan Client', self._same_day_birthday(self.today),
        )
        self._run_cron()  # must not raise
        self.assertFalse(self._logs(partner=orphan))

    def test_ineligible_contacts_never_notify(self):
        company = self._make_contact(
            'Company Client', self._same_day_birthday(self.today),
            user=self.manager_user, is_company=True,
        )
        colleague = self.env['res.users'].create({
            'name': 'Colleague',
            'login': 'pbr_colleague',
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        colleague.partner_id.write({
            'birthday': self._same_day_birthday(self.today),
            'user_id': self.manager_user.id,
        })
        self._run_cron()
        notified = self._logs(user=self.manager_user).mapped('partner_id')
        self.assertNotIn(company, notified)
        self.assertNotIn(colleague.partner_id, notified)

    def test_expired_activities_are_cleaned_up(self):
        self._run_cron()
        activity = self.env['mail.activity'].search([
            ('res_model', '=', 'res.partner'),
            ('res_id', '=', self.contact_tomorrow.id),
        ])
        self.assertTrue(activity)
        activity.date_deadline = self.today - timedelta(days=1)
        self.env['res.partner']._cleanup_overdue_birthday_activities()
        self.assertFalse(activity.exists())

    def test_foreign_activities_are_left_alone(self):
        foreign = self.env['mail.activity'].create({
            'res_model_id': self.env.ref('base.model_res_partner').id,
            'res_id': self.contact_today.id,
            'activity_type_id': self.env.ref('mail.mail_activity_data_todo').id,
            'summary': 'Call about renewal',
            'date_deadline': self.today - timedelta(days=1),
            'user_id': self.manager_user.id,
        })
        self.env['res.partner']._cleanup_overdue_birthday_activities()
        self.assertTrue(
            foreign.exists(),
            "Housekeeping must only remove this module's own To Dos.",
        )

    def test_email_is_sent_to_the_account_manager(self):
        with self.mock_mail_gateway():
            self._run_cron()
        recipients = {
            recipient
            for mail in self._mails
            for recipient in mail.get('email_to') or []
        }
        self.assertTrue(
            any(self.manager_user.email in recipient for recipient in recipients),
            "Each interval sends one templated email to the Account Manager; "
            "got %s" % recipients,
        )
        self.assertFalse(
            any(self.contact_today.email in recipient for recipient in recipients),
            "The contact themselves must never be emailed by this module.",
        )

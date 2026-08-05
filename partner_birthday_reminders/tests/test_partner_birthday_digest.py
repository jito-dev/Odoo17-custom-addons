from datetime import timedelta

from odoo import fields
from odoo.tests.common import tagged

from .common import PartnerBirthdayCommon


@tagged('post_install', '-at_install')
class TestPartnerBirthdayDigest(PartnerBirthdayCommon):
    """The monthly digest."""

    def setUp(self):
        super().setUp()
        self.today = fields.Date.context_today(self.env.user)
        self.month_start = self.today.replace(day=1)
        # A birthday guaranteed to fall inside the current month.
        self.contact = self._make_contact(
            'Digest Client', self._same_day_birthday(self.today),
            user=self.manager_user,
        )
        self.pref = self.Pref._ensure_prefs_for_users(self.manager_user)
        self.pref.notify_monthly_digest = True

    def test_digest_sends_once_per_month(self):
        with self.mock_mail_gateway():
            self.env['res.partner']._cron_partner_birthday_digest()
        first_batch = len(self._new_mails)
        self.assertTrue(first_batch, "The digest email must be sent.")
        self.assertEqual(self.pref.last_digest_date, self.month_start)

        with self.mock_mail_gateway():
            self.env['res.partner']._cron_partner_birthday_digest()
        self.assertFalse(
            self._new_mails,
            "Re-running the monthly cron must be a no-op — the guard is "
            "last_digest_date, so 'Run Manually' is safe.",
        )

    def test_digest_is_opt_in(self):
        self.pref.notify_monthly_digest = False
        with self.mock_mail_gateway():
            self.env['res.partner']._cron_partner_birthday_digest()
        self.assertFalse(
            self._new_mails,
            "A manager who did not opt in must receive no digest.",
        )

    def test_empty_month_still_stamps(self):
        """No birthdays this month → no mail, but the month is marked done."""
        self.contact.birthday = False
        with self.mock_mail_gateway():
            self.env['res.partner']._cron_partner_birthday_digest()
        self.assertFalse(self._new_mails)
        self.assertEqual(
            self.pref.last_digest_date, self.month_start,
            "Without the stamp, the digest would fire later in the month "
            "as soon as any contact gained a birthday.",
        )

    def test_digest_lists_only_this_managers_contacts(self):
        other_contact = self._make_contact(
            'Other Manager Client', self._same_day_birthday(self.today),
            user=self.other_user,
        )
        partners = self.env['res.partner']._birthday_partners_in_month(
            self.manager_user, self.month_start,
        )
        self.assertIn(self.contact, partners)
        self.assertNotIn(other_contact, partners)

    def test_digest_covers_whole_month_not_just_today(self):
        """A birthday later this month belongs in the digest."""
        later = self.month_start + timedelta(days=20)
        if later.month != self.month_start.month:
            later = self.month_start
        late_contact = self._make_contact(
            'Late Month Client', self._same_day_birthday(later),
            user=self.manager_user,
        )
        partners = self.env['res.partner']._birthday_partners_in_month(
            self.manager_user, self.month_start,
        )
        self.assertIn(late_contact, partners)

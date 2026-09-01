from datetime import date

from odoo.tests.common import tagged

from .common import PartnerBirthdayCommon


@tagged('post_install', '-at_install')
class TestPartnerBirthdayEligibility(PartnerBirthdayCommon):
    """The eligibility rule is the module's contract — pin every clause."""

    def test_plain_contact_is_eligible(self):
        contact = self._make_contact('Clara Client', date(1990, 5, 17))
        self.assertTrue(contact.birthday_eligible)
        self.assertFalse(contact.has_internal_user)

    def test_contact_without_birthday_is_excluded(self):
        contact = self._make_contact('No Birthday')
        self.assertFalse(contact.birthday_eligible)

    def test_company_is_excluded(self):
        company = self._make_contact(
            'Acme Corp', date(1990, 5, 17), is_company=True,
        )
        self.assertFalse(company.birthday_eligible)

    def test_current_internal_user_is_excluded(self):
        user = self.env['res.users'].create({
            'name': 'Ivan Internal',
            'login': 'pbr_internal',
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        user.partner_id.birthday = date(1990, 5, 17)
        self.assertTrue(user.partner_id.has_internal_user)
        self.assertFalse(user.partner_id.birthday_eligible)

    def test_past_internal_user_is_excluded(self):
        """Archiving the user must not turn a colleague into a client."""
        user = self.env['res.users'].create({
            'name': 'Olga Former',
            'login': 'pbr_former',
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        partner = user.partner_id
        partner.birthday = date(1990, 5, 17)
        user.active = False
        self.assertTrue(
            partner.has_internal_user,
            "An archived internal user is still a past internal user.",
        )
        self.assertFalse(partner.birthday_eligible)

    def test_past_internal_user_survives_cron_refresh(self):
        """The daily self-heal must not re-admit an archived colleague."""
        user = self.env['res.users'].create({
            'name': 'Petro Former',
            'login': 'pbr_former2',
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        partner = user.partner_id
        partner.birthday = date(1990, 5, 17)
        user.active = False
        self.Partner._refresh_partner_birthday_helpers()
        self.assertFalse(partner.birthday_eligible)

    def test_portal_user_contact_stays_eligible(self):
        """Only *internal* users are excluded — portal contacts are clients."""
        portal_group = self.env.ref('base.group_portal')
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Petra Portal',
            'login': 'pbr_portal',
            'groups_id': [(6, 0, [portal_group.id])],
        })
        user.partner_id.birthday = date(1990, 5, 17)
        self.assertFalse(user.partner_id.has_internal_user)
        self.assertTrue(user.partner_id.birthday_eligible)

    def test_archived_contact_is_excluded(self):
        contact = self._make_contact('Zoe Archived', date(1990, 5, 17))
        contact.active = False
        self.assertFalse(contact.birthday_eligible)

    def test_next_birthday_is_always_today_or_later(self):
        today = self._local_today()
        contact = self._make_contact('Rollover', date(1990, 1, 1))
        self.assertGreaterEqual(contact.next_birthday, today)
        self.assertEqual(
            (contact.next_birthday.month, contact.next_birthday.day), (1, 1),
        )

    def test_proximity_buckets(self):
        today = self._local_today()
        born_today = self._make_contact(
            'Today Contact', self._same_day_birthday(today),
        )
        self.assertEqual(born_today.birthday_proximity, '1_today')
        self.assertEqual(born_today.next_birthday, today)

    def test_feb29_falls_back_to_feb28_in_non_leap_year(self):
        contact = self._make_contact('Leapling', date(1992, 2, 29))
        # 2027 is not a leap year.
        occurrence = contact._birthday_next_occurrence(date(2027, 1, 1))
        self.assertEqual(occurrence, date(2027, 2, 28))
        # 2028 is.
        occurrence = contact._birthday_next_occurrence(date(2028, 1, 1))
        self.assertEqual(occurrence, date(2028, 2, 29))

    def test_matching_picks_feb29_contacts_on_feb28(self):
        contact = self._make_contact('Leapling Match', date(1992, 2, 29))
        matched = self.Partner._partners_with_birthday_on(date(2027, 2, 28))
        self.assertIn(contact, matched)
        matched_leap = self.Partner._partners_with_birthday_on(date(2028, 2, 29))
        self.assertIn(contact, matched_leap)

    def test_matching_only_returns_eligible_contacts(self):
        eligible = self._make_contact('Match Me', date(1990, 3, 3))
        company = self._make_contact(
            'Match Corp', date(1990, 3, 3), is_company=True,
        )
        matched = self.Partner._partners_with_birthday_on(date(2027, 3, 3))
        self.assertIn(eligible, matched)
        self.assertNotIn(company, matched)

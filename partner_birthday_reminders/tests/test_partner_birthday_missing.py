from datetime import date

from odoo.tests.common import tagged

from .common import PartnerBirthdayCommon


@tagged('post_install', '-at_install')
class TestPartnerBirthdayMissingScreen(PartnerBirthdayCommon):
    """The Missing Birthdays domain and counters."""

    def _missing_domain(self):
        action = self.env.ref(
            'partner_birthday_reminders.action_partner_birthdays_missing'
        )
        return action.domain

    def test_action_domain_is_the_inverse_of_eligibility(self):
        missing = self._make_contact('Needs A Date', user=self.manager_user)
        filled = self._make_contact(
            'Has A Date', date(1990, 2, 2), user=self.manager_user,
        )
        company = self.env['res.partner'].create({
            'name': 'Excluded Corp', 'is_company': True,
        })
        colleague = self.manager_user.partner_id

        found = self.env['res.partner'].search(
            eval(self._missing_domain())  # noqa: S307 - trusted module data
        )
        self.assertIn(missing, found)
        self.assertNotIn(filled, found, "A filled birthday is not 'missing'.")
        self.assertNotIn(company, found, "Companies have no birthday.")
        self.assertNotIn(
            colleague, found,
            "Internal users are colleagues — they belong to the HR module.",
        )

    def test_missing_counter_tracks_own_contacts_only(self):
        self._make_contact('Mine Without Date', user=self.manager_user)
        self._make_contact('Theirs Without Date', user=self.other_user)
        pref = self.Pref._ensure_prefs_for_users(self.manager_user)
        pref.invalidate_recordset(['missing_birthday_count'])
        mine = self.env['res.partner'].search_count([
            ('is_company', '=', False),
            ('active', '=', True),
            ('has_internal_user', '=', False),
            ('birthday', '=', False),
            ('user_id', '=', self.manager_user.id),
        ])
        self.assertEqual(pref.missing_birthday_count, mine)
        self.assertGreaterEqual(mine, 1)

    def test_filling_a_birthday_moves_the_contact_to_the_board(self):
        contact = self._make_contact('Moves Over', user=self.manager_user)
        self.assertFalse(contact.birthday_eligible)
        contact.birthday = date(1991, 9, 9)
        self.assertTrue(
            contact.birthday_eligible,
            "Filling the date on the Missing screen must make the contact "
            "appear on the Birthdays board immediately.",
        )

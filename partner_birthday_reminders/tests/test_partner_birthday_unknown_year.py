from datetime import date

from odoo.tests.common import tagged

from ..models.constants import BIRTHDAY_UNKNOWN_YEAR
from .common import PartnerBirthdayCommon


@tagged('post_install', '-at_install')
class TestPartnerBirthdayUnknownYear(PartnerBirthdayCommon):
    """The 'birth year unknown' flag."""

    def test_year_normalised_on_create(self):
        contact = self._make_contact(
            'No Year Client', date(1987, 4, 21), birthday_year_unknown=True,
        )
        self.assertEqual(contact.birthday.year, BIRTHDAY_UNKNOWN_YEAR)
        self.assertEqual((contact.birthday.month, contact.birthday.day), (4, 21))

    def test_year_normalised_when_flag_set_later(self):
        contact = self._make_contact('Later Flag Client', date(1987, 4, 22))
        self.assertEqual(contact.birthday.year, 1987)
        contact.birthday_year_unknown = True
        self.assertEqual(contact.birthday.year, BIRTHDAY_UNKNOWN_YEAR)

    def test_feb_29_survives_normalisation(self):
        """The sentinel year is a leap year, so Feb 29 is storable."""
        contact = self._make_contact(
            'Leapling Client', date(1988, 2, 29), birthday_year_unknown=True,
        )
        self.assertEqual(
            (contact.birthday.month, contact.birthday.day), (2, 29),
            "Feb 29 must not be silently shifted by the unknown-year "
            "normalisation — that is why the sentinel is a leap year.",
        )

    def test_unknown_year_contact_is_still_reminded(self):
        """The engine has always ignored the year; that must still hold."""
        today = self._local_today()
        contact = self._make_contact(
            'Unknown Year Birthday', self._same_day_birthday(today),
            user=self.manager_user, birthday_year_unknown=True,
        )
        self.assertEqual(contact.birthday.year, BIRTHDAY_UNKNOWN_YEAR)
        self.assertTrue(contact.birthday_eligible)

        self.env['res.partner']._cron_partner_birthday_reminders()

        self.assertTrue(self.env['partner.birthday.log'].search([
            ('partner_id', '=', contact.id),
        ]), "A contact with an unknown birth year must still be reminded.")

    def test_flag_without_birthday_is_inert(self):
        contact = self._make_contact(
            'Flag Only Client', birthday_year_unknown=True,
        )
        self.assertFalse(contact.birthday)
        self.assertFalse(contact.birthday_eligible)

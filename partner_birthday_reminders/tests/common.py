from datetime import date

from odoo.addons.mail.tests.common import MailCommon


class PartnerBirthdayCommon(MailCommon):
    """Shared fixtures for the contact-birthday test suite.

    Built on ``MailCommon`` so tests can assert on outgoing mail through
    ``mock_mail_gateway()`` instead of hitting a real SMTP server.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Partner = cls.env['res.partner']
        cls.Pref = cls.env['partner.birthday.pref']
        cls.Log = cls.env['partner.birthday.log']

        cls.manager_user = cls.env['res.users'].create({
            'name': 'Anna Manager',
            'login': 'pbr_manager',
            'email': 'anna.manager@example.com',
            'tz': 'Europe/Kyiv',
            'groups_id': [(6, 0, [cls.env.ref('base.group_user').id])],
        })
        cls.other_user = cls.env['res.users'].create({
            'name': 'Boris Manager',
            'login': 'pbr_other',
            'email': 'boris.manager@example.com',
            'tz': 'Europe/Kyiv',
            'groups_id': [(6, 0, [cls.env.ref('base.group_user').id])],
        })

    @classmethod
    def _make_contact(cls, name, birthday=None, user=None, **kwargs):
        vals = {
            'name': name,
            'is_company': False,
            'email': '%s@example.com' % name.lower().replace(' ', '.'),
        }
        if birthday:
            vals['birthday'] = birthday
        if user:
            vals['user_id'] = user.id
        vals.update(kwargs)
        return cls.env['res.partner'].create(vals)

    @staticmethod
    def _birthday_on(reference, month, day):
        """A birthday date in the past with the given month/day."""
        return date(reference.year - 30, month, day)

    @staticmethod
    def _same_day_birthday(day, years_ago=30):
        """Birthday falling on the same day/month as ``day``, 30 years back.

        Feb 29 is shifted to Feb 28 when the target year is not a leap
        year, so the suite is runnable on any calendar day.
        """
        try:
            return day.replace(year=day.year - years_ago)
        except ValueError:
            return day.replace(year=day.year - years_ago, day=28)

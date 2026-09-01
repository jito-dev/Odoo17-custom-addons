from datetime import date

from odoo import fields
from odoo.addons.mail.tests.common import MailCommon


class PartnerBirthdayCommon(MailCommon):
    """Shared fixtures for the contact-birthday test suite.

    Built on ``MailCommon`` so tests can assert on outgoing mail through
    ``mock_mail_gateway()`` instead of hitting a real SMTP server.
    """

    # One timezone for the whole suite, admin included. The module computes
    # its day per user (``_birthday_local_today(pref)``), so two users in
    # different zones legitimately live on different dates for part of every
    # day - and a fixture built for one of them then fails against the other
    # for reasons that have nothing to do with the behaviour under test.
    # Timezone routing is a property of the model and is tested there; here
    # it is held constant on purpose. Give a user their own tz only in a test
    # that is *about* timezones, and build that test's dates for that user.
    TEST_TZ = 'Europe/Kyiv'

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # The fixtures below are keyed to a *local* day, because that is what the
        # module works in: the cron reads `_birthday_local_today(pref)`, the
        # timezone of the preference owner. The test admin has no tz of its own,
        # so it is UTC, and between 21:00 and 24:00 UTC its date is already a day
        # behind Kyiv's - which silently shifted every interval, routing, digest
        # and scope assertion in this suite by one day for three hours a night.
        # Giving the admin ``TEST_TZ`` too puts the fixtures, the cron and
        # the model code that reads `self.env.user` (`_cleanup_overdue_birthday_
        # activities`, `_compute_birthday_helpers`) all on the same calendar day,
        # whatever the clock says. Use `_local_today()` rather than
        # `fields.Date.context_today(self.env.user)` in tests.
        cls.env.user.tz = cls.TEST_TZ

        cls.Partner = cls.env['res.partner']
        cls.Pref = cls.env['partner.birthday.pref']
        cls.Log = cls.env['partner.birthday.log']

        cls.manager_user = cls.env['res.users'].create({
            'name': 'Anna Manager',
            'login': 'pbr_manager',
            'email': 'anna.manager@example.com',
            'tz': cls.TEST_TZ,
            'groups_id': [(6, 0, [cls.env.ref('base.group_user').id])],
        })
        cls.other_user = cls.env['res.users'].create({
            'name': 'Boris Manager',
            'login': 'pbr_other',
            'email': 'boris.manager@example.com',
            'tz': cls.TEST_TZ,
            'groups_id': [(6, 0, [cls.env.ref('base.group_user').id])],
        })

    @classmethod
    def _local_today(cls, user=None):
        """Today in the timezone of the user the reminders are run for.

        The anchor for every date fixture in the suite. Defaults to
        ``manager_user``, the owner of the preferences under test, so a
        fixture cannot drift from the day the cron will compute for that
        same user.
        """
        return fields.Date.context_today(user or cls.manager_user)

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

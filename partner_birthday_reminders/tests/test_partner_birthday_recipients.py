from datetime import date

from odoo.tests.common import tagged

from ..models.constants import PARAM_FALLBACK_USERS
from .common import PartnerBirthdayCommon


@tagged('post_install', '-at_install')
class TestPartnerBirthdayFallback(PartnerBirthdayCommon):
    """The recipient fallback chain.

    The critical property is the *default*: with nothing configured,
    ``birthday_manager_ids`` must equal ``user_id`` exactly, so the
    fallback can never quietly redirect somebody else's reminders.
    """

    def setUp(self):
        super().setUp()
        # Reset explicitly instead of trusting the default: assertions
        # about the "unconfigured" state must not depend on what an
        # earlier test left behind.
        self._set_fallback(False)

    def _set_fallback(self, fallback_user):
        self.env['ir.config_parameter'].sudo().set_param(
            PARAM_FALLBACK_USERS, str(fallback_user.id) if fallback_user else '',
        )
        self.env['res.partner']._refresh_partner_birthday_managers()

    def test_default_is_identical_to_user_id(self):
        """No configuration → recipient is the Account Manager, full stop."""
        assigned = self._make_contact(
            'Assigned Client', date(1990, 3, 12), user=self.manager_user,
        )
        orphan = self._make_contact('Orphan Client', date(1990, 3, 13))
        self.assertEqual(assigned.birthday_manager_ids, self.manager_user)
        self.assertFalse(
            orphan.birthday_manager_ids,
            "With no fallback configured an unassigned contact must have "
            "no recipient at all.",
        )

    def test_company_inheritance_is_core_behaviour(self):
        """Odoo itself inherits the salesperson from the parent company.

        Pinned as a test because it is the reason this module ships *no*
        "inherit from company" option: ``res.partner.user_id`` is a
        stored, precomputed field whose core ``_compute_user_id`` copies
        the parent company's salesperson onto any person contact that has
        none. A setting of ours would duplicate it — and could not switch
        it off. If a future Odoo version drops this, the test fails and
        the decision gets revisited.
        """
        company = self.env['res.partner'].create({
            'name': 'Acme Corp',
            'is_company': True,
            'user_id': self.manager_user.id,
        })
        child = self._make_contact(
            'Acme Employee', date(1990, 5, 4), parent_id=company.id,
        )
        self.assertEqual(
            child.user_id, self.manager_user,
            "Odoo core is expected to inherit user_id from the company.",
        )
        self.assertEqual(child.birthday_manager_ids, self.manager_user)

    def test_own_manager_always_wins_over_fallback(self):
        child = self._make_contact(
            'Owned Client', date(1990, 6, 4), user=self.manager_user,
        )
        self._set_fallback(self.other_user)
        child.invalidate_recordset(['birthday_manager_ids'])
        self.assertEqual(
            child.birthday_manager_ids, self.manager_user,
            "An explicit Account Manager must never be overridden by the "
            "fallback.",
        )

    def test_global_fallback_user(self):
        orphan = self._make_contact('Nobody Client', date(1990, 7, 4))
        self._set_fallback(self.other_user)
        orphan.invalidate_recordset(['birthday_manager_ids'])
        self.assertEqual(orphan.birthday_manager_ids, self.other_user)

    def test_archived_fallback_user_is_ignored(self):
        """An archived fallback stops receiving without touching settings."""
        orphan = self._make_contact('Stale Fallback Client', date(1990, 8, 4))
        self._set_fallback(self.other_user)
        orphan.invalidate_recordset(['birthday_manager_ids'])
        self.assertEqual(orphan.birthday_manager_ids, self.other_user)

        self.other_user.active = False
        self.env['res.partner']._refresh_partner_birthday_managers()
        orphan.invalidate_recordset(['birthday_manager_ids'])
        self.assertFalse(orphan.birthday_manager_ids)

    def test_fallback_recipient_actually_receives(self):
        """End to end: the fallback user gets the reminder, not nobody."""
        today = self._local_today()
        orphan = self._make_contact(
            'Fallback Birthday Client', self._same_day_birthday(today),
        )
        self._set_fallback(self.other_user)
        orphan.invalidate_recordset(['birthday_manager_ids'])

        self.env['res.partner']._cron_partner_birthday_reminders()

        logs = self.env['partner.birthday.log'].search([
            ('partner_id', '=', orphan.id),
            ('user_id', '=', self.other_user.id),
        ])
        self.assertTrue(
            logs, "The configured fallback user must receive the reminder.",
        )

from datetime import date

from odoo.tests.common import tagged

from ..models.constants import PARAM_FALLBACK_USERS
from .common import PartnerBirthdayCommon


@tagged('post_install', '-at_install')
class TestPartnerBirthdayGreeter(PartnerBirthdayCommon):
    """The greeter chain.

    ``birthday_greeter_id`` → ``user_id`` → Default Greeter → nobody.

    The point of the new field is that steering birthday reminders must
    never require editing ``user_id`` (Salesperson), which drives sales
    reporting, lead assignment and record rules.
    """

    def setUp(self):
        super().setUp()
        self._set_default_greeter(False)
        self.third_user = self.env['res.users'].create({
            'name': 'Clara Greeter',
            'login': 'pbr_greeter',
            'email': 'clara.greeter@example.com',
            'tz': self.TEST_TZ,
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id])],
        })

    def _set_default_greeter(self, user):
        self.env['ir.config_parameter'].sudo().set_param(
            PARAM_FALLBACK_USERS, str(user.id) if user else '',
        )
        self.env['res.partner']._refresh_partner_birthday_managers()

    # -- 1. greeter wins -------------------------------------------------
    def test_greeter_overrides_salesperson(self):
        contact = self._make_contact(
            'Greeter Wins', date(1990, 3, 3), user=self.manager_user,
            birthday_greeter_id=self.third_user.id,
        )
        self.assertEqual(contact.birthday_manager_ids, self.third_user)
        self.assertEqual(
            contact.user_id, self.manager_user,
            "Setting a greeter must not touch Salesperson — that is the "
            "whole reason the field exists.",
        )

    # -- 2. no behaviour change when unused ------------------------------
    def test_empty_greeter_falls_back_to_salesperson(self):
        contact = self._make_contact(
            'No Greeter', date(1990, 4, 4), user=self.manager_user,
        )
        self.assertFalse(contact.birthday_greeter_id)
        self.assertEqual(contact.birthday_manager_ids, self.manager_user)

    # -- 3. archived greeter falls through, does not go silent -----------
    def test_archived_greeter_falls_through(self):
        contact = self._make_contact(
            'Archived Greeter', date(1990, 5, 5), user=self.manager_user,
            birthday_greeter_id=self.third_user.id,
        )
        self.assertEqual(contact.birthday_manager_ids, self.third_user)

        self.third_user.active = False
        self.env['res.partner']._refresh_partner_birthday_managers()
        contact.invalidate_recordset(['birthday_manager_ids'])
        self.assertEqual(
            contact.birthday_manager_ids, self.manager_user,
            "An archived greeter must fall through to the Salesperson, "
            "not silently stop the reminder.",
        )

    def test_portal_greeter_falls_through(self):
        portal = self.env['res.users'].with_context(
            no_reset_password=True,
        ).create({
            'name': 'Portal Person',
            'login': 'pbr_portal_greeter',
            'email': 'portal.greeter@example.com',
            'groups_id': [(6, 0, [self.env.ref('base.group_portal').id])],
        })
        contact = self._make_contact(
            'Portal Greeter', date(1990, 6, 6), user=self.manager_user,
            birthday_greeter_id=portal.id,
        )
        self.assertEqual(
            contact.birthday_manager_ids, self.manager_user,
            "A portal user is not a colleague and must never be a "
            "reminder recipient.",
        )

    # -- 4. the dangerous one -------------------------------------------
    def test_deleting_greeter_user_does_not_delete_the_contact(self):
        """``ondelete='set null'`` — a cascade here would delete clients.

        Also pins the staleness that follows: PostgreSQL nulls both
        ``birthday_greeter_id`` and the stored ``birthday_manager_ids``
        underneath the ORM, which therefore does not recompute. The
        recipient reads empty until the next refresh.

        That is safe rather than merely tolerated: every cron tick calls
        ``_refresh_partner_birthday_helpers()`` *before* deciding whom to
        notify, so the stale value can never cause a misdelivery — it can
        only make the board look wrong for up to a day.
        """
        contact = self._make_contact(
            'Survives Deletion', date(1990, 7, 7), user=self.manager_user,
            birthday_greeter_id=self.third_user.id,
        )
        contact_id = contact.id
        self.third_user.unlink()

        survivor = self.env['res.partner'].browse(contact_id).exists()
        self.assertTrue(
            survivor,
            "Deleting the greeter user must NOT delete the contact — a "
            "cascade from res.users to res.partner would destroy "
            "customer records.",
        )
        self.assertFalse(survivor.birthday_greeter_id)

        self.env['res.partner']._refresh_partner_birthday_managers()
        survivor.invalidate_recordset(['birthday_manager_ids'])
        self.assertEqual(
            survivor.birthday_manager_ids, self.manager_user,
            "Once refreshed, the chain must fall through to the "
            "Salesperson.",
        )

    # -- 5. default greeter ---------------------------------------------
    def test_default_greeter_catches_the_unassigned(self):
        orphan = self._make_contact('Unowned Contact', date(1990, 8, 8))
        self.assertFalse(orphan.birthday_manager_ids)

        self._set_default_greeter(self.third_user)
        orphan.invalidate_recordset(['birthday_manager_ids'])
        self.assertEqual(orphan.birthday_manager_ids, self.third_user)

    def test_several_default_greeters_all_receive(self):
        """The last step of the chain may be plural.

        The point is coverage without stamping: several people cover the
        whole base and no contact record is touched.
        """
        today = self._local_today()
        orphan = self._make_contact(
            'Shared Client', self._same_day_birthday(today),
        )
        self.env['ir.config_parameter'].sudo().set_param(
            PARAM_FALLBACK_USERS,
            '%s,%s' % (self.manager_user.id, self.third_user.id),
        )
        self.env['res.partner']._refresh_partner_birthday_managers()
        orphan.invalidate_recordset(['birthday_manager_ids'])

        self.assertEqual(
            orphan.birthday_manager_ids,
            self.manager_user | self.third_user,
        )
        self.assertFalse(
            orphan.birthday_greeter_id,
            "Nothing may be written onto the contact — avoiding that "
            "manual stamping is the whole reason this exists.",
        )

        self.env['res.partner']._cron_partner_birthday_reminders()
        for user in (self.manager_user, self.third_user):
            self.assertTrue(
                self.Log.search([
                    ('partner_id', '=', orphan.id),
                    ('user_id', '=', user.id),
                ]),
                "Every Default Greeter must get their own reminder — the "
                "log key includes the user, so one row each.",
            )

    def test_archived_default_greeter_drops_out_of_the_list(self):
        orphan = self._make_contact('Partly Stale', date(1990, 8, 15))
        self.env['ir.config_parameter'].sudo().set_param(
            PARAM_FALLBACK_USERS,
            '%s,%s' % (self.manager_user.id, self.third_user.id),
        )
        self.env['res.partner']._refresh_partner_birthday_managers()
        orphan.invalidate_recordset(['birthday_manager_ids'])
        self.assertEqual(len(orphan.birthday_manager_ids), 2)

        self.third_user.active = False
        self.env['res.partner']._refresh_partner_birthday_managers()
        orphan.invalidate_recordset(['birthday_manager_ids'])
        self.assertEqual(
            orphan.birthday_manager_ids, self.manager_user,
            "Archiving one Default Greeter must not silence the others.",
        )

    def test_default_greeter_never_overrides_an_explicit_one(self):
        contact = self._make_contact(
            'Explicit Greeter', date(1990, 9, 9),
            birthday_greeter_id=self.manager_user.id,
        )
        self._set_default_greeter(self.third_user)
        contact.invalidate_recordset(['birthday_manager_ids'])
        self.assertEqual(contact.birthday_manager_ids, self.manager_user)

    # -- 6. settings recompute immediately -------------------------------
    def test_settings_save_recomputes_recipients(self):
        orphan = self._make_contact('Settings Recompute', date(1990, 10, 10))
        self.assertFalse(orphan.birthday_manager_ids)

        settings = self.env['res.config.settings'].create({
            'partner_birthday_fallback_user_ids': [(6, 0, self.third_user.ids)],
        })
        settings.execute()

        orphan.invalidate_recordset(['birthday_manager_ids'])
        self.assertEqual(
            orphan.birthday_manager_ids, self.third_user,
            "Saving Settings must recompute the stored recipient at once; "
            "waiting for the nightly cron would make the board lie.",
        )

    def test_settings_reports_paused_default_greeter(self):
        """The silent killer: one paused row stops the whole base."""
        pref = self.Pref._ensure_prefs_for_users(self.third_user)
        pref.active = False
        self._set_default_greeter(self.third_user)

        settings = self.env['res.config.settings'].create({
            'partner_birthday_fallback_user_ids': [(6, 0, self.third_user.ids)],
        })
        settings._compute_partner_birthday_coverage()
        self.assertTrue(
            settings.partner_birthday_greeter_paused,
            "A paused Default Greeter must be surfaced in Settings — "
            "otherwise reminders stop for every contact with no error "
            "anywhere.",
        )

    # -- 7. field security ----------------------------------------------
    def test_greeter_field_is_not_readable_by_portal_users(self):
        portal = self.env['res.users'].with_context(
            no_reset_password=True,
        ).create({
            'name': 'Nosy Portal',
            'login': 'pbr_portal_reader',
            'email': 'nosy.portal@example.com',
            'groups_id': [(6, 0, [self.env.ref('base.group_portal').id])],
        })
        self._make_contact('Private Data', date(1990, 11, 11))
        fields_for_portal = self.env['res.partner'].with_user(
            portal,
        ).fields_get()
        for fname in ('birthday', 'birthday_greeter_id', 'birthday_manager_ids'):
            self.assertNotIn(
                fname, fields_for_portal,
                "%s is personal data and must stay invisible to portal "
                "users, including in the ORM prefetch batch." % fname,
            )

    # -- 8. reassignment between intervals -------------------------------
    def test_reassignment_reminds_the_new_greeter(self):
        """Accepted trade-off: both may greet, rather than nobody."""
        today = self._local_today()
        contact = self._make_contact(
            'Reassigned Client', self._same_day_birthday(today),
            user=self.manager_user,
        )
        self.env['res.partner']._cron_partner_birthday_reminders()
        self.assertTrue(self.Log.search([
            ('partner_id', '=', contact.id),
            ('user_id', '=', self.manager_user.id),
        ]), "The original recipient should have been reminded.")

        contact.birthday_greeter_id = self.third_user
        # Clear the per-user day stamps so the cron reprocesses today.
        self.Pref.with_context(active_test=False).search([]).write({
            'last_run_date': False,
        })
        self.env['res.partner']._cron_partner_birthday_reminders()

        self.assertTrue(self.Log.search([
            ('partner_id', '=', contact.id),
            ('user_id', '=', self.third_user.id),
        ]), "After reassignment the new greeter must also be reminded — "
            "suppressing them risks nobody greeting the contact.")

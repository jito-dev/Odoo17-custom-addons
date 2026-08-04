from odoo import _, api, fields, models

from .constants import (
    GROUP_MANAGER_XMLID,
    PARAM_DEFAULT_1_DAY,
    PARAM_DEFAULT_7_DAYS,
    PARAM_DEFAULT_ON_DAY,
)


class PartnerBirthdayPref(models.Model):
    """Per-Account-Manager reminder preferences.

    Unlike ``hr_birthday_reminders``, this record is **not** a roster:
    who receives a reminder is derived from ``res.partner.user_id``
    (the Account Manager), never from this table. A preference row only
    answers two questions for one user:

    * which of the three intervals do they want, and are they paused?
    * have we already processed their reminders on their local today
      (``last_run_date``, keyed on ``res.users.tz``)?

    Rows are auto-provisioned by the daily cron for every internal user
    who is the Account Manager of at least one eligible contact, using
    the defaults from *Settings → Contact Birthday Reminders*. Nobody
    has to remember to "subscribe" — assigning a contact is enough.
    Deleting a row is therefore harmless: the next cron tick recreates
    it with the default intervals. To stop receiving reminders, pause
    the row (``active = False``) rather than deleting it — the cron
    honours paused rows and never resurrects them.
    """

    _name = 'partner.birthday.pref'
    _description = 'Contact Birthday Reminder Preferences'
    _rec_name = 'user_id'
    _order = 'user_id'

    user_id = fields.Many2one(
        comodel_name='res.users',
        string='Account Manager',
        required=True,
        ondelete='cascade',
        index=True,
        default=lambda self: self.env.user,
        help="The user these preferences belong to. They receive "
             "reminders for every contact they are the Account Manager "
             "of (res.partner.user_id).",
    )
    notify_7_days_before = fields.Boolean(
        string='Notify 7 days before',
        default=True,
        help="Receive a To Do activity, an inbox notification and an "
             "email 7 days before the birthday.",
    )
    notify_1_day_before = fields.Boolean(
        string='Notify 1 day before',
        default=True,
        help="Receive a To Do activity, an inbox notification and an "
             "email the day before the birthday.",
    )
    notify_on_day = fields.Boolean(
        string='Notify on the day',
        default=True,
        help="Receive an inbox notification and an email on the birthday "
             "itself. No To Do activity — there is nothing left to "
             "prepare on the day.",
    )
    active = fields.Boolean(
        default=True,
        help="Uncheck to pause all contact birthday reminders for this "
             "user. Paused rows are skipped by the cron and are never "
             "auto-recreated, so pausing is the supported way to opt "
             "out (deleting the row only lasts until the next run).",
    )
    user_tz = fields.Selection(
        related='user_id.tz',
        readonly=True,
        string='Timezone',
        help="Read-only echo of the user's preferences. Determines the "
             "timezone in which the cron decides whether 'today' has "
             "already been processed for this user. Empty falls back "
             "to UTC.",
    )
    last_run_date = fields.Date(
        string='Last run',
        readonly=True,
        copy=False,
        help="Local date (in the user's timezone) on which the cron last "
             "processed this user. Guarantees one dispatch per local day "
             "regardless of how often the cron fires.",
    )
    contact_count = fields.Integer(
        string='Contacts with a birthday',
        compute='_compute_contact_count',
        help="How many eligible contacts this user is the Account "
             "Manager of. Zero means the user currently receives "
             "nothing, even with reminders enabled.",
    )
    is_editable_by_current_user = fields.Boolean(
        string='Editable by me',
        compute='_compute_is_editable_by_current_user',
        compute_sudo=False,
        help="UI helper: True when the current user may edit this row — "
             "their own row, or they hold the Contact Birthday Manager "
             "role, or they are a Settings administrator. Record rules "
             "enforce the same thing at DB level; this field only makes "
             "non-editable rows render greyed-out instead of failing on "
             "save.",
    )

    _sql_constraints = [
        (
            'uniq_user',
            'unique(user_id)',
            'This user already has a contact birthday preference row.',
        ),
    ]

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------
    @api.depends('user_id')
    def _compute_contact_count(self):
        Partner = self.env['res.partner'].sudo()
        for pref in self:
            pref.contact_count = Partner.search_count([
                ('birthday_eligible', '=', True),
                ('user_id', '=', pref.user_id.id),
            ]) if pref.user_id else 0

    @api.depends('user_id')
    def _compute_is_editable_by_current_user(self):
        """Drive the readonly bindings on the tree/form views.

        ``compute_sudo=False`` is critical — under sudo the admin checks
        would always answer True and every row would look editable.
        """
        user = self.env.user
        uid = self.env.uid
        is_admin = (
            user.has_group(GROUP_MANAGER_XMLID)
            or user.has_group('base.group_system')
        )
        for pref in self:
            pref.is_editable_by_current_user = is_admin or pref.user_id.id == uid

    # ------------------------------------------------------------------
    # Provisioning
    # ------------------------------------------------------------------
    @api.model
    def _default_interval_values(self):
        """Interval defaults for auto-provisioned rows, from Settings."""
        icp = self.env['ir.config_parameter'].sudo()

        def _flag(key):
            # Unset parameter → True, so a fresh install reminds on all
            # three intervals (matching the field defaults).
            return icp.get_param(key, 'True') not in ('False', 'false', '0', '')

        return {
            'notify_7_days_before': _flag(PARAM_DEFAULT_7_DAYS),
            'notify_1_day_before': _flag(PARAM_DEFAULT_1_DAY),
            'notify_on_day': _flag(PARAM_DEFAULT_ON_DAY),
        }

    @api.model
    def _ensure_prefs_for_users(self, users):
        """Create missing preference rows for ``users``; return all rows.

        Idempotent and safe to call on every cron tick. ``active_test=False``
        on the lookup is essential: a paused row must be recognised as
        existing, otherwise the UNIQUE constraint would blow up — and,
        worse, a user who deliberately paused would be silently
        re-subscribed.
        """
        users = users.filtered(lambda u: u.active and not u.share)
        if not users:
            return self.browse()
        Pref = self.sudo().with_context(active_test=False)
        existing = Pref.search([('user_id', 'in', users.ids)])
        missing = users - existing.mapped('user_id')
        if missing:
            defaults = self._default_interval_values()
            existing |= Pref.create([
                dict(defaults, user_id=user.id) for user in missing
            ])
        return existing

    # ------------------------------------------------------------------
    # UX helpers
    # ------------------------------------------------------------------
    def action_open_contacts(self):
        """Open this user's eligible contacts (stat button / tree link)."""
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'partner_birthday_reminders.action_partner_birthdays'
        )
        action['domain'] = [
            ('birthday_eligible', '=', True),
            ('user_id', '=', self.user_id.id),
        ]
        action['context'] = {'search_default_group_by_proximity': 1}
        return action

    def name_get(self):
        result = []
        for pref in self:
            label = pref.user_id.name or _('Preferences')
            if not pref.active:
                label = _("%(name)s (paused)", name=label)
            result.append((pref.id, label))
        return result

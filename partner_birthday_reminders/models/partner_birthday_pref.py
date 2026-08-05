from odoo import _, api, fields, models

from .constants import (
    GROUP_MANAGER_XMLID,
    PARAM_DEFAULT_1_DAY,
    PARAM_DEFAULT_7_DAYS,
    PARAM_DEFAULT_DIGEST,
    PARAM_DEFAULT_ON_DAY,
)


class PartnerBirthdayPref(models.Model):
    """Per-Account-Manager reminder preferences.

    Unlike ``hr_birthday_reminders``, this record is **not** a roster:
    who receives a reminder is derived from the contact, never from this
    table. A preference row only
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
    # -- How (channels) -------------------------------------------------
    # Each channel is independently refusable. The To Do matters most:
    # activities are a work queue, and a client birthday is not work for
    # everyone.
    channel_activity = fields.Boolean(
        string='To Do activity',
        default=True,
        help="Create a To Do on the contact, due on the birthday. Only "
             "for the 7-day and 1-day reminders — there is nothing left "
             "to prepare on the day itself.",
    )
    channel_inbox = fields.Boolean(
        string='Discuss notification',
        default=True,
        help="Send a private note to your Odoo inbox. Nothing is posted "
             "on the contact's chatter, so the sales team does not see "
             "it.",
    )
    channel_email = fields.Boolean(
        string='Email',
        default=True,
        help="Send the reminder to your email address. Does not affect "
             "the monthly digest, which has its own switch.",
    )
    has_no_channel = fields.Boolean(
        string='No channel enabled',
        compute='_compute_has_no_channel',
        help="UI helper: every channel is switched off, so this row "
             "emits nothing — the same effect as pausing it.",
    )

    # -- When -----------------------------------------------------------
    shift_weekend_reminders = fields.Boolean(
        string='Shift weekend reminders to Friday',
        default=False,
        help="When a reminder would arrive on a Saturday or Sunday, "
             "deliver it on the preceding Friday instead. Applies to the "
             "7-day and 1-day reminders only: moving 'today is their "
             "birthday' to Friday would simply make it wrong.",
    )

    # -- Which contacts -------------------------------------------------
    scope = fields.Selection(
        selection=[
            ('all', 'All contacts I receive'),
            ('owned_only', 'Only contacts I own'),
        ],
        string='Scope',
        default='all',
        required=True,
        help="'Only contacts I own' limits reminders to contacts where "
             "you are the Birthday Greeter or the Salesperson, excluding "
             "the ones you merely catch as the global Default Greeter. "
             "Without this, becoming the Default Greeter is an "
             "all-or-nothing commitment to the entire contact base.",
    )

    notify_monthly_digest = fields.Boolean(
        string='Monthly digest',
        default=False,
        help="Receive one email on the 1st of each month listing every "
             "contact of yours with a birthday that month. Planning "
             "context, not a reminder — it does not replace the "
             "per-birthday notifications above. Off by default: a second "
             "outbound channel should be opted into, not inherited.",
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
    last_digest_date = fields.Date(
        string='Last digest',
        readonly=True,
        copy=False,
        help="First day of the month whose digest was last sent to this "
             "user, in their timezone. Guarantees one digest per month "
             "however often the monthly cron is run.",
    )
    contact_count = fields.Integer(
        string='Contacts with a birthday',
        compute='_compute_contact_count',
        help="How many eligible contacts this user is the reminder "
             "recipient for. Zero means the user currently receives "
             "nothing, even with reminders enabled.",
    )
    missing_birthday_count = fields.Integer(
        string='Contacts missing a birthday',
        compute='_compute_missing_birthday_count',
        help="How many of this user's contacts are people with no "
             "birthday recorded. These are invisible to the reminder "
             "engine until the date is filled in.",
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
                ('birthday_manager_ids', 'in', pref.user_id.id),
            ]) if pref.user_id else 0

    @api.depends('channel_activity', 'channel_inbox', 'channel_email')
    def _compute_has_no_channel(self):
        for pref in self:
            pref.has_no_channel = not (
                pref.channel_activity or pref.channel_inbox or pref.channel_email
            )

    @api.depends('user_id')
    def _compute_missing_birthday_count(self):
        """Count this user's contacts that a birthday would make eligible.

        Domain is the eligibility rule with the birthday clause inverted,
        so the two screens cannot drift. Assignment is read from
        ``user_id`` rather than ``birthday_manager_ids``: the fallback
        chain would attribute thousands of unassigned contacts to the
        fallback user, which is noise on a "what should I fill in?"
        counter.
        """
        Partner = self.env['res.partner'].sudo()
        for pref in self:
            pref.missing_birthday_count = Partner.search_count([
                ('is_company', '=', False),
                ('active', '=', True),
                ('has_internal_user', '=', False),
                ('birthday', '=', False),
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
            # Digest defaults to False, unlike the three intervals: a
            # second outbound channel must be opted into deliberately.
            'notify_monthly_digest': icp.get_param(
                PARAM_DEFAULT_DIGEST, 'False',
            ) in ('True', 'true', '1'),
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
    @api.model
    def action_open_my_preferences(self):
        """Open the current user's own row as a form, never a list.

        A regular user's record rule shows them exactly one row, so the
        list view rendered "my settings" as a one-line table — which is
        what made the screen look purposeless.

        The row is created on demand rather than only by the cron:
        otherwise the screen is empty until the first nightly run, and a
        user who wants to opt out *before* the first reminder arrives has
        nothing to switch off.
        """
        pref = self.with_context(active_test=False).search([
            ('user_id', '=', self.env.uid),
        ], limit=1)
        if not pref:
            # sudo() only for the write: the record rule permits creating
            # one's own row, but reading the Settings defaults touches
            # ir.config_parameter, which regular users cannot read.
            pref = self.sudo().create(dict(
                self._default_interval_values(), user_id=self.env.uid,
            ))
        return {
            'type': 'ir.actions.act_window',
            'name': _('My Birthday Reminders'),
            'res_model': 'partner.birthday.pref',
            'view_mode': 'form',
            'res_id': pref.id,
            'target': 'current',
            'context': {'active_test': False},
        }

    def action_open_contacts(self):
        """Open this user's eligible contacts (stat button / tree link)."""
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'partner_birthday_reminders.action_partner_birthdays'
        )
        action['domain'] = [
            ('birthday_eligible', '=', True),
            ('birthday_manager_ids', 'in', self.user_id.id),
        ]
        action['context'] = {'search_default_group_by_proximity': 1}
        return action

    def action_open_missing_birthdays(self):
        """Open this user's contacts that still need a birthday."""
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'partner_birthday_reminders.action_partner_birthdays_missing'
        )
        action['domain'] = [
            ('is_company', '=', False),
            ('active', '=', True),
            ('has_internal_user', '=', False),
            ('birthday', '=', False),
            ('user_id', '=', self.user_id.id),
        ]
        return action

    def name_get(self):
        result = []
        for pref in self:
            label = pref.user_id.name or _('Preferences')
            if not pref.active:
                label = _("%(name)s (paused)", name=label)
            result.append((pref.id, label))
        return result

from odoo import _, api, fields, models


GROUP_RESPONSIBLE_XMLID = 'hr_birthday_reminders.group_birthday_responsible'

# Users we never auto-flip to ``notification_type='inbox'``:
# ``base.user_root`` and ``base.user_admin`` are reloaded by
# ``base/data/res_users_data.xml`` whenever ``-u base`` runs. That XML
# temporarily clears their groups (``Command.set([])``), turning them
# share=True for the duration of the flush. The mail constraint
# ``CHECK (notification_type='email' OR NOT share)`` then refuses any
# row carrying ``inbox``, breaking workspace startup.
SYSTEM_USER_XMLIDS = ('base.user_root', 'base.user_admin')


class BirthdayReminderSubscription(models.Model):
    """Per-user birthday reminder subscription.

    A subscription record IS the assignment of the
    ``group_birthday_responsible`` role: creating one adds the user to the
    group, archiving or unlinking removes them. This single source of truth
    keeps the role and the per-user reminder preferences in lock-step.

    Each Responsible chooses which of the three intervals (7 days
    before, 1 day before, on the day) they want. The daily cron in
    ``hr.employee`` iterates every active subscription once per UTC
    day and processes any whose ``last_run_date`` is not the user's
    local today. The exact UTC hour at which the cron fires is a
    system-wide setting (``Settings → Birthday Reminders → Daily run
    hour (UTC)``).
    """

    _name = 'birthday.reminder.subscription'
    _description = 'Birthday Reminder Subscription'
    _rec_name = 'user_id'
    _order = 'user_id'

    user_id = fields.Many2one(
        comodel_name='res.users',
        string='Responsible',
        required=True,
        ondelete='cascade',
        index=True,
        help="The user who will receive this reminder schedule.",
    )
    notify_7_days_before = fields.Boolean(
        string='Notify 7 days before',
        default=True,
        help="Receive a To Do activity 7 days before each employee's birthday.",
    )
    notify_1_day_before = fields.Boolean(
        string='Notify 1 day before',
        default=True,
        help="Receive a To Do activity 1 day before each employee's birthday.",
    )
    notify_on_day = fields.Boolean(
        string='Notify on the day',
        default=True,
        help="Receive a chatter message and an email on the day of each "
             "employee's birthday.",
    )
    user_tz = fields.Selection(
        related='user_id.tz',
        readonly=True,
        string='Timezone',
        help="Read-only echo of the user's preferences. Determines the "
             "timezone in which the daily cron decides whether 'today' "
             "has already been processed for this user. If empty, UTC "
             "is used.",
    )
    last_run_date = fields.Date(
        string='Last run',
        readonly=True,
        copy=False,
        help="Local date (in the user's timezone) on which the cron last "
             "processed this subscription. Used to avoid running twice on "
             "the same day even if the cron fires multiple times.",
    )
    active = fields.Boolean(
        default=True,
        help="Uncheck to temporarily pause this subscription. The user is "
             "removed from the Responsible group while paused.",
    )
    # v17.0.2.23.0 — UI helper for per-row editability on the
    # Responsibles tree/form views. Non-stored compute so it always
    # reflects the *current* user's permissions (stored would be
    # nonsensical — the answer depends on env.user). compute_sudo=False
    # is critical: with sudo the answer would always be True (root).
    is_editable_by_current_user = fields.Boolean(
        string='Editable by me',
        compute='_compute_is_editable_by_current_user',
        compute_sudo=False,
        help="UI helper. True when the current user can edit this "
             "subscription — i.e. it's their own subscription, or they "
             "have the Birthday Reminders Manager role, or they are a "
             "Settings (base.group_system) admin. Drives readonly "
             "bindings on the tree and form views. Defence in depth: "
             "DB-level record rules still enforce the actual write "
             "protection, this field only affects UI presentation.",
    )

    _sql_constraints = [
        (
            'uniq_user',
            'unique(user_id)',
            'A subscription already exists for this user.',
        ),
    ]

    # ------------------------------------------------------------------
    # UI helper compute
    # ------------------------------------------------------------------
    @api.depends('user_id')
    def _compute_is_editable_by_current_user(self):
        """Drive UI readonly-bindings on Responsibles views.

        True when the current user can edit this subscription. The
        actual write permission is still enforced at DB-level by the
        record rules in security/birthday_security.xml; this compute
        is purely a UI hint so non-editable rows render greyed-out
        instead of letting the user attempt a write that would fail
        with AccessError.

        Cached at the env level (compute_sudo=False) — admin checks
        are evaluated once per env, then applied to every record on
        the page.
        """
        user = self.env.user
        uid = self.env.uid
        is_admin = (
            user.has_group('hr_birthday_reminders.group_birthday_manager')
            or user.has_group('base.group_system')
        )
        for rec in self:
            rec.is_editable_by_current_user = (
                is_admin or rec.user_id.id == uid
            )

    # ------------------------------------------------------------------
    # Group-membership synchronisation
    # ------------------------------------------------------------------
    def _sync_responsible_group(self, users):
        """Reconcile ``group_birthday_responsible`` membership for users.

        Membership tracks the **existence** of a subscription (active or
        paused), NOT its ``active`` flag. Pausing is a temporary "skip
        me in the cron" signal — the role stays so the user can keep
        reading/editing their own record (and unpause later). Removing
        the group on pause locks the user out of the very record they
        just paused.

        - subscription exists  → user in group
        - no subscription      → user not in group
        - active=True/False    → group membership unchanged
        - unlink               → if no other sub remains, leave group
        """
        if not users:
            return
        group = self.env.ref(GROUP_RESPONSIBLE_XMLID, raise_if_not_found=False)
        if not group:
            return
        # v17.0.2.32.0: search_count without active_test=False used to
        # silently exclude paused subscriptions, contradicting the
        # docstring contract ("active=True/False → group membership
        # unchanged"). The original create/write hooks never exposed
        # the bug because they only fired on user_id changes, not on
        # pause toggling. The v17.0.2.31.0 daily self-heal cron does
        # call this method unconditionally, which makes the bug
        # visible: pausing your own subscription would silently
        # remove you from the group on the next cron tick.
        Sub = self.sudo().with_context(active_test=False)
        for user in users:
            has_any = Sub.search_count([('user_id', '=', user.id)])
            in_group = user in group.users
            if has_any and not in_group:
                group.sudo().write({'users': [(4, user.id)]})
            elif not has_any and in_group:
                group.sudo().write({'users': [(3, user.id)]})

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        recs._sync_responsible_group(recs.mapped('user_id'))
        # Default Odoo `notification_type` is 'email', which makes our
        # chatter messages skip the Discuss-Inbox entirely. New
        # Responsibles almost certainly want in-app notifications too,
        # so flip them to 'inbox'. They can still revert via Preferences
        # if they really only want email.
        system_ids = {
            self.env.ref(xid).id
            for xid in SYSTEM_USER_XMLIDS
            if self.env.ref(xid, raise_if_not_found=False)
        }
        for sub in recs:
            user = sub.user_id
            if user.id in system_ids:
                continue
            if user.share:
                continue
            if user.notification_type != 'inbox':
                user.sudo().write({'notification_type': 'inbox'})
        return recs

    def write(self, vals):
        # Only re-assignment (user_id change) requires group sync now —
        # pausing/un-pausing via `active` no longer toggles membership.
        affected_users = self.env['res.users']
        if 'user_id' in vals:
            affected_users |= self.mapped('user_id')  # original users
        res = super().write(vals)
        if 'user_id' in vals and vals.get('user_id'):
            affected_users |= self.env['res.users'].browse(vals['user_id'])
        if affected_users:
            self._sync_responsible_group(affected_users)
        return res

    def unlink(self):
        affected_users = self.mapped('user_id')
        res = super().unlink()
        self._sync_responsible_group(affected_users)
        return res

    # ------------------------------------------------------------------
    # UX helpers
    # ------------------------------------------------------------------
    def name_get(self):
        result = []
        for sub in self:
            label = sub.user_id.name or _('Subscription')
            if not sub.active:
                label = _("%(name)s (paused)", name=label)
            result.append((sub.id, label))
        return result

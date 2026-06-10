import calendar
import logging
from datetime import timedelta

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.misc import format_date

_logger = logging.getLogger(__name__)


TODO_ACTIVITY_XMLID = 'mail.mail_activity_data_todo'

INTERVAL_7_DAYS = '7_days'
INTERVAL_1_DAY = '1_day'
INTERVAL_ON_DAY = 'on_day'
# Greeting is a system-emitted, employee-facing event (not tied to any
# Responsible). Log rows use base.user_root as user_id so the existing
# UNIQUE (employee, date, interval, user_id) constraint guarantees one
# greeting attempt per employee per day.
INTERVAL_GREETING = 'greeting'

GREETING_FAILED_TEMPLATE_XMLID = (
    'hr_birthday_reminders.mail_template_birthday_greeting_failed'
)
GREETING_ENABLED_PARAM = 'hr_birthday_reminders.greeting_enabled'

# Health-watchdog / alerting (v17.0.2.30.0).
ALERT_ENABLED_PARAM = 'hr_birthday_reminders.alert_enabled'
ALERT_REPEAT_HOURS_PARAM = 'hr_birthday_reminders.alert_repeat_hours'
ALERT_LAST_STATUS_PARAM = 'hr_birthday_reminders.alert_last_status'
ALERT_LAST_AT_PARAM = 'hr_birthday_reminders.alert_last_at'
ALERT_DEGRADED_TEMPLATE_XMLID = (
    'hr_birthday_reminders.mail_template_birthday_health_alert'
)
ALERT_RECOVERED_TEMPLATE_XMLID = (
    'hr_birthday_reminders.mail_template_birthday_health_recovered'
)
ALERT_SEVERITY_TRIGGERS = ('danger',)
DEFAULT_ALERT_REPEAT_HOURS = 24

# Per-interval email templates. Each is rendered against an
# ``hr.employee`` record and sent once per Responsible (one
# ``mail.mail`` row per recipient, with ``email_to`` overridden in
# ``_send_birthday_email``). The greeting template is the one rendered
# for the employee themselves — same model, different audience.
EMAIL_TEMPLATE_XMLIDS = {
    INTERVAL_7_DAYS:  'hr_birthday_reminders.mail_template_birthday_7_days',
    INTERVAL_1_DAY:   'hr_birthday_reminders.mail_template_birthday_1_day',
    INTERVAL_ON_DAY:  'hr_birthday_reminders.mail_template_birthday_today',
    INTERVAL_GREETING: 'hr_birthday_reminders.mail_template_birthday_to_employee',
}


class HrEmployee(models.Model):
    """Birthday-reminder hooks on hr.employee.

    The daily cron iterates every active ``birthday.reminder.subscription``
    record and, for each, decides whether to process based on
    ``last_run_date`` (in the user's local timezone). On the first
    firing of each user's local day, the per-subscription dispatcher
    emits the per-user notifications for the three intervals the
    subscription has enabled.

    All employee data is read via ``sudo()`` because the ``birthday`` field
    is gated on ``hr.group_hr_user`` and Responsibles do not have that
    group — they only have ``base.group_user`` plus our own
    ``group_birthday_responsible``.
    """

    _inherit = 'hr.employee'

    # ------------------------------------------------------------------
    # Birthday-proximity helpers (stored compute, refreshed by cron)
    # ------------------------------------------------------------------
    # Both fields depend on "today" — a value the ORM dependency tracker
    # does not know about. They are stored so they sort/group natively
    # in SQL, and the daily cron calls _refresh_birthday_helpers() to
    # re-run the compute after midnight rolls over.
    next_birthday = fields.Date(
        string='Next Birthday',
        compute='_compute_birthday_helpers',
        store=True,
        compute_sudo=True,
        help="Date of the next upcoming occurrence of the employee's "
             "birthday — today or later. Feb 29 falls back to Feb 28 "
             "in non-leap years.",
    )
    # Numeric prefix on Selection keys is intentional: Odoo's group_by
    # over a Selection field sorts the resulting kanban groups by the
    # internal key alphabetically, NOT by the order declared here.
    # Without the prefix the user sees Later → This Week → Today →
    # Tomorrow (alphabetical), which inverts the desired urgency order.
    # Labels remain plain; only the keys carry the sort weight.
    birthday_proximity = fields.Selection(
        selection=[
            ('1_today', '🎂 Today'),
            ('2_tomorrow', '🗓️ Tomorrow'),
            ('3_this_week', '📅 Within 7 Days'),
            ('4_later', '⏳ Later'),
        ],
        string='Birthday Proximity',
        compute='_compute_birthday_helpers',
        store=True,
        compute_sudo=True,
        help="Bucket used by the Birthday Reminders kanban grouping. "
             "Empty for employees without a birthday set.",
    )
    # Today-only marker for the Employees views: success/failure of the
    # auto-greeting email sent to the employee themselves. Empty for any
    # employee whose birthday is not today (compute returns False), so
    # the badge widget naturally hides for non-today rows without needing
    # column-level invisible attributes.
    birthday_greeting_state = fields.Selection(
        selection=[
            ('sent', '✅ Sent'),
            ('failed', '⚠️ Failed'),
        ],
        string='Today Greeting',
        compute='_compute_birthday_greeting_state',
        store=True,
        compute_sudo=True,
        help="Result of the automatic birthday greeting sent to the "
             "employee. Populated only on the actual birthday — empty "
             "on any other day. Refreshed by the daily cron after the "
             "greeting attempt completes.",
    )

    @api.depends('birthday')
    def _compute_birthday_helpers(self):
        """Recompute next_birthday + birthday_proximity for each record.

        sudo() on the read so Responsibles (without hr.group_hr_user) can
        still trigger the compute via cron / view refresh.
        """
        today = fields.Date.context_today(self.env.user)
        for emp in self:
            emp_su = emp.sudo()
            b = emp_su.birthday
            if not b:
                emp.next_birthday = False
                emp.birthday_proximity = False
                continue
            nb = emp_su._birthday_next_occurrence(today)
            emp.next_birthday = nb
            if not nb:
                emp.birthday_proximity = False
                continue
            days = (nb - today).days
            if days == 0:
                emp.birthday_proximity = '1_today'
            elif days == 1:
                emp.birthday_proximity = '2_tomorrow'
            elif days <= 7:
                emp.birthday_proximity = '3_this_week'
            else:
                emp.birthday_proximity = '4_later'

    @api.depends('birthday_proximity')
    def _compute_birthday_greeting_state(self):
        """Project the latest greeting Log row onto each today-employee.

        Non-today employees always get False — so badge widgets and
        kanban chips naturally show nothing for them. For today
        employees we read the latest birthday.reminder.log row keyed
        on (employee_id, today, interval='greeting') and echo its
        greeting_status. sudo() is required because Responsibles do
        not own greeting rows (user_id=base.user_root.id) — the
        per-user record rule would otherwise hide them.
        """
        today = fields.Date.context_today(self.env.user)
        Log = self.env['birthday.reminder.log'].sudo()
        for emp in self:
            if emp.birthday_proximity != '1_today':
                emp.birthday_greeting_state = False
                continue
            row = Log.search(
                [
                    ('employee_id', '=', emp.id),
                    ('birthday_date', '=', today),
                    ('interval', '=', INTERVAL_GREETING),
                ],
                order='notified_at desc',
                limit=1,
            )
            emp.birthday_greeting_state = row.greeting_status or False

    def _birthday_next_occurrence(self, today):
        """Return the next future occurrence of self.birthday on/after today.

        Feb 29 in a non-leap target year falls back to Feb 28 — same
        policy as the cron, so calendar and notifications agree.
        """
        self.ensure_one()
        b = self.sudo().birthday
        if not b:
            return False

        def _safe(year):
            try:
                return b.replace(year=year)
            except ValueError:
                return b.replace(year=year, day=28)

        occ = _safe(today.year)
        if occ < today:
            occ = _safe(today.year + 1)
        return occ

    @api.model
    def _refresh_birthday_helpers(self):
        """Recompute stored next_birthday / birthday_proximity using
        the current server-local 'today'. Called from the daily cron so
        the kanban / tree default_order stays fresh after midnight.
        """
        employees = self.sudo().search([('birthday', '!=', False)])
        if not employees:
            return
        employees.invalidate_recordset(['next_birthday', 'birthday_proximity'])
        employees._compute_birthday_helpers()
        employees.flush_recordset(['next_birthday', 'birthday_proximity'])

    @api.model
    def _refresh_greeting_state_today(self, today):
        """Recompute birthday_greeting_state for today's birthday employees.

        Run after _send_employee_greetings created its Log rows: the
        compute does not depend on Log records (the ORM has no way to
        track that), so we must invalidate + recompute manually for the
        chip-marker to flip from empty → sent/failed within the same
        cron transaction.
        """
        emps = self._employees_with_birthday_on(today)
        if not emps:
            return
        # Make sure any in-flight Log.create rows are materialised before
        # the compute search hits the DB.
        self.env['birthday.reminder.log'].sudo().flush_model()
        emps.invalidate_recordset(['birthday_greeting_state'])
        emps._compute_birthday_greeting_state()
        emps.flush_recordset(['birthday_greeting_state'])

    @api.model
    def _cleanup_overdue_birthday_activities(self):
        """Drop mail.activity rows whose deadline has passed.

        Activities are scheduled with ``date_deadline = target_date`` —
        i.e. the actual birthday date. Once `today >= deadline`:
        - 7d / 1d reminders have served their purpose (the on-day
          chatter+email takes over today); the residual activity is
          noise on the Responsible's dashboard.
        - Strictly-past deadlines are stale leftovers from prior runs.

        Match heuristic: ``summary ILIKE 'Upcoming birthday%'``. The
        prefix is set by ``_schedule_birthday_activity`` and is currently
        in English; under a different user language the summary would
        be localised and miss this filter. Acceptable for single-lang
        deployments — switch to a custom activity_type_id or a marker
        field on mail.activity if multi-lang cleanup becomes a need.
        """
        today = fields.Date.context_today(self.env.user)
        Activity = self.env['mail.activity'].sudo()
        overdue = Activity.search([
            ('res_model', '=', 'hr.employee'),
            ('summary', 'ilike', 'Upcoming birthday%'),
            ('date_deadline', '<=', today),
        ])
        if overdue:
            _logger.info(
                "Birthday reminders cleanup: deleting %d expired "
                "activity/ies (deadline <= %s).",
                len(overdue), today,
            )
            overdue.unlink()

    # ------------------------------------------------------------------
    # Cron entry-point
    # ------------------------------------------------------------------
    @api.model
    def _cron_birthday_reminders(self):
        """Daily entry-point.

        Fires once per day at the configured UTC hour (see
        ``ir.config_parameter`` ``hr_birthday_reminders.cron_hour_utc``).
        Iterates every active subscription and processes any whose
        ``last_run_date`` is not the user's local "today".

        ``pytz`` is still used to compute the user's local date because
        ``last_run_date`` is keyed on local-day in the user's own
        timezone — this means a Responsible east of the cron UTC hour
        is processed during their morning, while one far west is
        processed late on their previous calendar day. Idempotency is
        absolute either way.
        """
        # Tidy up activities whose deadline has passed (or hits today —
        # by today the on-day chatter+email replaces them). Done before
        # processing so the Responsible's Activities widget reflects only
        # what is still actionable.
        self._cleanup_overdue_birthday_activities()

        # Refresh stored next_birthday / birthday_proximity for the
        # Employees views (compute depends on "today", which only changes
        # via cron firings, not via field writes). The @api.depends chain
        # also re-fires birthday_greeting_state — so the chip-marker
        # picks up any Log rows produced by the separately-scheduled
        # greetings cron (see _cron_birthday_greetings_to_employees).
        self._refresh_birthday_helpers()

        # v17.0.2.31.0: defensive self-heal of group membership. ``-u base``
        # periodically strips custom groups from base.user_admin (see the
        # v17.0.2.29.0 / v17.0.2.30.0 migrations) and the version-bump
        # migrations only restore it once per upgrade. Running the same
        # reconciliation daily here means any drift introduced by a -u base
        # in the meantime self-corrects within 24 hours, without the user
        # needing to know about it.
        self._birthday_self_heal_group_membership()

        Sub = self.env['birthday.reminder.subscription'].sudo()
        subs = Sub.search([('active', '=', True)])
        for sub in subs:
            try:
                self._birthday_maybe_run_for_subscription(sub)
            except Exception:
                # One bad subscription must never block the rest.
                _logger.exception(
                    "Birthday reminders: failed processing subscription "
                    "#%s (user=%s).", sub.id, sub.user_id.id,
                )

    # ------------------------------------------------------------------
    # Greetings cron entry-point (v17.0.2.16.0)
    # ------------------------------------------------------------------
    @api.model
    def _cron_birthday_greetings_to_employees(self):
        """Dedicated daily entry-point for the employee greeting flow.

        Runs at its own UTC hour (Settings → Birthday Reminders →
        "Greeting hour (UTC)"), independently of the per-Responsible
        reminders cron. Independent of subscriptions — sends greetings
        even when no Responsibles are configured.

        Idempotency is unchanged: birthday.reminder.log row gated on
        (employee_id, today, interval='greeting',
        user_id=base.user_root.id), so re-runs (manual or accidental
        same-day) produce zero new emails / log rows.
        """
        self._refresh_birthday_helpers()
        today = fields.Date.context_today(self.env.user)
        try:
            self._send_employee_greetings(today)
        except Exception:
            _logger.exception(
                "Birthday greetings cron: _send_employee_greetings crashed."
            )
        try:
            self._refresh_greeting_state_today(today)
        except Exception:
            _logger.exception(
                "Birthday greetings cron: _refresh_greeting_state_today crashed."
            )

    # ------------------------------------------------------------------
    # Self-heal of group membership (v17.0.2.31.0)
    # ------------------------------------------------------------------
    @api.model
    def _birthday_self_heal_group_membership(self):
        """Reconcile ``group_birthday_responsible`` against subscriptions.

        Drift between the group and the set of subscription holders is
        introduced reliably by ``-u base`` (which sets
        ``Command.set([])`` on ``base.user_admin.groups_id``) and
        occasionally by manual fiddling. The v17.0.2.29.0 and
        v17.0.2.30.0 migrations re-sync once per version bump, but a
        ``-u base`` between bumps leaves admin out of the group until
        somebody upgrades the module again or runs a shell command.

        Running the same reconciliation daily from the reminders cron
        means any drift self-corrects within 24 hours — admin never
        permanently loses access to the Birthday Reminders menu. The
        helper is idempotent: when no drift exists, zero writes happen,
        and nothing is logged. When drift is found, one INFO line
        records what changed for later auditing.

        Wrapped in try/except so a self-heal failure (extremely
        unlikely, but possible if the group record is deleted) never
        cascades and blocks the main reminders flow.
        """
        try:
            Sub = self.env['birthday.reminder.subscription'].sudo()
            group = self.env.ref(
                'hr_birthday_reminders.group_birthday_responsible',
                raise_if_not_found=False,
            )
            if not group:
                return
            target_users = group.users | Sub.search([]).user_id
            if not target_users:
                return
            before_ids = set(group.users.ids)
            Sub._sync_responsible_group(target_users)
            # Refresh after the sync — the relation cache may still
            # hold the pre-sync set, force re-read.
            group.invalidate_recordset(['users'])
            after_ids = set(group.users.ids)
            added = after_ids - before_ids
            removed = before_ids - after_ids
            if added or removed:
                _logger.info(
                    "Birthday reminders self-heal: group_birthday_responsible "
                    "added %d user(s) %s, removed %d user(s) %s.",
                    len(added), sorted(added),
                    len(removed), sorted(removed),
                )
        except Exception:
            # Self-heal failure must never block the reminders cron.
            _logger.exception(
                "Birthday reminders self-heal: group sync failed "
                "(non-fatal — main cron continues)."
            )

    # ------------------------------------------------------------------
    # Health watchdog cron (v17.0.2.30.0)
    # ------------------------------------------------------------------
    @api.model
    def _cron_birthday_health_watchdog(self):
        """Periodic health check + alert when the dashboard turns red.

        Fires every 6 hours. Reads ``birthday.reminder.health`` and
        decides whether to email admins + managers based on three
        transitions:

        * ``ok → danger``  → emit one ``degraded`` alert
        * ``danger → danger``, last alert was > repeat_hours ago →
          emit another ``degraded`` alert (escalation nag)
        * ``danger → ok``  → emit one ``recovered`` alert

        ``warning`` is intentionally below threshold — yellow shows in
        the dashboard, but a one-cycle hiccup is not worth waking
        anybody. Severity is hardcoded as a tuple constant for v1; a
        Settings knob can promote it later.

        Anti-spam state is two ICP keys (``alert_last_status`` +
        ``alert_last_at``) — cheap, no schema. Recovery resets last_at.
        """
        ICP = self.env['ir.config_parameter'].sudo()
        if not str(ICP.get_param(ALERT_ENABLED_PARAM, 'True')).lower() in (
            '1', 'true', 'yes',
        ):
            return

        rec = self.env['birthday.reminder.health'].sudo().create({})
        current = rec.overall_status or 'danger'
        last_status = ICP.get_param(ALERT_LAST_STATUS_PARAM, 'none')
        last_at_str = ICP.get_param(ALERT_LAST_AT_PARAM, '')
        try:
            repeat_hours = int(
                ICP.get_param(
                    ALERT_REPEAT_HOURS_PARAM, str(DEFAULT_ALERT_REPEAT_HOURS),
                )
            )
        except (TypeError, ValueError):
            repeat_hours = DEFAULT_ALERT_REPEAT_HOURS

        is_alerting = current in ALERT_SEVERITY_TRIGGERS
        was_alerting = last_status in ALERT_SEVERITY_TRIGGERS

        emit_degraded = False
        emit_recovered = False
        if is_alerting and not was_alerting:
            emit_degraded = True
        elif is_alerting and was_alerting:
            last_at = fields.Datetime.from_string(last_at_str) if last_at_str else None
            if last_at and (
                fields.Datetime.now() - last_at
            ).total_seconds() / 3600.0 >= repeat_hours:
                emit_degraded = True
        elif not is_alerting and was_alerting:
            emit_recovered = True

        if emit_degraded:
            self._send_birthday_health_alert('degraded', rec)
            ICP.set_param(
                ALERT_LAST_AT_PARAM,
                fields.Datetime.to_string(fields.Datetime.now()),
            )
        elif emit_recovered:
            self._send_birthday_health_alert('recovered', rec)
            # Clear last_at so the next degraded transition fires
            # immediately rather than waiting for repeat_hours.
            ICP.set_param(ALERT_LAST_AT_PARAM, '')

        # Always update last_status so repeated invocations within
        # the same status stay correctly tracked.
        ICP.set_param(ALERT_LAST_STATUS_PARAM, current)

    @api.model
    def _assemble_alert_audience(self):
        """Union of system admins + Birthday Reminders Managers.

        Deduplicated by partner_id — a single user with both groups
        receives one notification, not two.
        """
        sys_group = self.env.ref(
            'base.group_system', raise_if_not_found=False,
        )
        mgr_group = self.env.ref(
            'hr_birthday_reminders.group_birthday_manager',
            raise_if_not_found=False,
        )
        users = self.env['res.users'].sudo()
        if sys_group:
            users |= sys_group.users
        if mgr_group:
            users |= mgr_group.users
        # Exclude inactive users + base.user_root (cron-only).
        root = self.env.ref('base.user_root', raise_if_not_found=False)
        users = users.filtered(
            lambda u: u.active and (not root or u.id != root.id)
        )
        return users.partner_id

    @api.model
    def _send_birthday_health_alert(self, kind, health_record):
        """Emit one alert (degraded or recovered) to admins + managers.

        Creates a persistent ``birthday.reminder.alert`` row so the
        ``message_notify`` call has something stable to anchor to
        (TransientModel records would be auto-vacuumed and break the
        Inbox link). Then sends inbox + email to every partner in the
        audience.
        """
        if kind not in ('degraded', 'recovered'):
            raise ValueError(f"unknown alert kind: {kind!r}")
        partners = self._assemble_alert_audience()
        if not partners:
            _logger.warning(
                "Birthday health alert: no admins or managers to notify "
                "(group_system AND group_birthday_manager are both empty)."
            )
            return

        Alert = self.env['birthday.reminder.alert'].sudo()
        alert = Alert.create({
            'kind': kind,
            'overall_status': health_record.overall_status or '',
            'overall_message': health_record.overall_message or '',
            'notified_partner_ids': [(6, 0, partners.ids)],
        })

        template_xmlid = (
            ALERT_DEGRADED_TEMPLATE_XMLID if kind == 'degraded'
            else ALERT_RECOVERED_TEMPLATE_XMLID
        )
        template = self.env.ref(template_xmlid, raise_if_not_found=False)
        if not template:
            _logger.error(
                "Birthday health alert: template %s missing — aborting.",
                template_xmlid,
            )
            return

        try:
            subject = template._render_field(
                'subject', alert.ids,
            )[alert.id]
            body = template._render_field(
                'body_html', alert.ids,
            )[alert.id]
        except Exception:
            _logger.exception(
                "Birthday health alert: template render failed."
            )
            subject = (
                "🔴 Birthday Reminders health degraded" if kind == 'degraded'
                else "✅ Birthday Reminders health recovered"
            )
            body = health_record.overall_message or ''

        # 1) Inbox notification on the persistent alert record.
        try:
            alert.message_notify(
                partner_ids=partners.ids,
                subject=subject,
                body=body,
                subtype_xmlid='mail.mt_note',
            )
        except Exception:
            _logger.exception(
                "Birthday health alert: message_notify failed."
            )

        # 2) Email each partner. Errors on one address must not block the
        # rest — the SMTP failure of one mailbox is exactly the kind of
        # thing we want the alert to bypass.
        for partner in partners:
            if not partner.email:
                continue
            try:
                template.send_mail(
                    alert.id, force_send=True,
                    email_values={'email_to': partner.email},
                )
            except Exception:
                _logger.exception(
                    "Birthday health alert: send_mail to %s failed.",
                    partner.email,
                )

    @api.model
    def _birthday_maybe_run_for_subscription(self, subscription):
        """Decide and run for a single subscription, in the user's tz.

        Skips only if we already ran today for this user
        (``last_run_date`` matches the user's local date). Otherwise
        runs the three intervals and stamps ``last_run_date`` so any
        manual re-runs the same local day are no-ops.
        """
        user_tz_name = subscription.user_id.tz or 'UTC'
        try:
            user_tz = pytz.timezone(user_tz_name)
        except pytz.UnknownTimeZoneError:
            _logger.warning(
                "Birthday reminders: subscription #%s has unknown tz '%s'; "
                "falling back to UTC.", subscription.id, user_tz_name,
            )
            user_tz = pytz.UTC

        now_utc = pytz.UTC.localize(fields.Datetime.now())
        now_local = now_utc.astimezone(user_tz)
        local_today = now_local.date()

        if subscription.last_run_date == local_today:
            return  # Already processed in this user's local day.

        self._birthday_process_subscription(subscription, local_today)
        subscription.sudo().write({'last_run_date': local_today})

    @api.model
    def _birthday_process_subscription(self, subscription, today):
        """Run the three intervals for one subscription."""
        if subscription.notify_7_days_before:
            self._process_birthday_interval(
                today + timedelta(days=7), INTERVAL_7_DAYS, subscription,
            )
        if subscription.notify_1_day_before:
            self._process_birthday_interval(
                today + timedelta(days=1), INTERVAL_1_DAY, subscription,
            )
        if subscription.notify_on_day:
            self._process_birthday_interval(
                today, INTERVAL_ON_DAY, subscription,
            )

    # ------------------------------------------------------------------
    # Birthday matching
    # ------------------------------------------------------------------
    @api.model
    def _employees_with_birthday_on(self, target_date):
        """Active employees whose birthday matches ``target_date`` on (day, month).

        Feb 29 fallback: in non-leap years where ``target_date`` is Feb 28,
        employees born on Feb 29 are also returned so they are not silently
        skipped 3 years out of every 4.
        """
        is_leap = calendar.isleap(target_date.year)
        feb29_fallback = (
            not is_leap
            and target_date.month == 2
            and target_date.day == 28
        )
        all_with_birthday = self.sudo().search([('birthday', '!=', False)])

        def matches(emp):
            b = emp.birthday
            if b.month == target_date.month and b.day == target_date.day:
                return True
            if feb29_fallback and b.month == 2 and b.day == 29:
                return True
            return False

        return all_with_birthday.filtered(matches)

    # ------------------------------------------------------------------
    # Per-interval orchestration (per subscription)
    # ------------------------------------------------------------------
    @api.model
    def _process_birthday_interval(self, target_date, interval_key, subscription):
        """Emit notifications for one subscription, one (target_date, interval) pair.

        The ``birthday.reminder.log`` table gates everything: each
        ``(employee, date, interval, user)`` combination is logged after a
        successful emit and skipped on subsequent runs. The UNIQUE
        constraint protects against parallel cron runs.
        """
        Log = self.env['birthday.reminder.log'].sudo()
        employees = self._employees_with_birthday_on(target_date)
        if not employees:
            return
        user = subscription.user_id
        for emp in employees:
            already = Log.search_count([
                ('employee_id', '=', emp.id),
                ('birthday_date', '=', target_date),
                ('interval', '=', interval_key),
                ('user_id', '=', user.id),
            ])
            if already:
                continue
            try:
                # Activity is only useful for upcoming-birthday intervals;
                # there is no actionable "todo" once the birthday is today.
                if interval_key in (INTERVAL_7_DAYS, INTERVAL_1_DAY):
                    self._schedule_birthday_activity(
                        emp, target_date, interval_key, user,
                    )
                # Inbox + email are sent for every interval so the channel
                # mix matches the spec regardless of the user's
                # ``notification_type`` preference.
                self._notify_birthday_user(
                    emp, target_date, user, interval_key,
                )
                self._send_birthday_email(emp, user, interval_key)
                Log.create({
                    'employee_id': emp.id,
                    'user_id': user.id,
                    'birthday_date': target_date,
                    'interval': interval_key,
                })
            except Exception:
                # One bad employee/user pair must never block the rest.
                _logger.exception(
                    "Birthday reminders: failed (emp=%s user=%s "
                    "interval=%s date=%s).",
                    emp.id, user.id, interval_key, target_date,
                )

    # ------------------------------------------------------------------
    # Side effects (per subscription user)
    # ------------------------------------------------------------------
    @api.model
    def _format_birthday_label(self, target_date, lang=None):
        """Localised 'dd MMMM' label — never includes the year (privacy)."""
        return format_date(
            self.env, target_date, date_format='dd MMMM', lang_code=lang,
        )

    @api.model
    def _schedule_birthday_activity(self, employee, target_date, interval_key, user):
        """Create one To Do activity for this subscription's user.

        ``mail_activity_quick_update=True`` suppresses Odoo's standard
        post-create assignment notification (``mail/models/mail_activity.py``
        line 333-337) — we ship our own friendly notification through
        ``_notify_birthday_user`` so the bare "X assigned to you" system
        message is redundant and was inconsistent across users (it
        respected each recipient's ``notification_type``, so admin saw
        it only in email while inbox-pref users saw it in Discuss).
        Skipping it gives every Responsible an identical inbox view.
        """
        when_text = (
            _('in 7 days') if interval_key == INTERVAL_7_DAYS else _('tomorrow')
        )
        emp_name = employee.sudo().name
        label = self._format_birthday_label(target_date, lang=user.lang)
        # Note text must only reference public hr.employee fields. The
        # assignee may be a Responsible without hr.group_hr_user and would
        # not be able to render anything beyond the public profile.
        note = _(
            "🎉 %(name)s has a birthday %(when)s (%(date)s). "
            "Please prepare congratulations.",
            name=emp_name,
            when=when_text,
            date=label,
        )
        employee.sudo().with_context(
            mail_activity_quick_update=True,
        ).activity_schedule(
            TODO_ACTIVITY_XMLID,
            date_deadline=target_date,
            summary=_("Upcoming birthday: %(name)s", name=emp_name),
            note=note,
            user_id=user.id,
        )

    @api.model
    def _notify_birthday_user(self, employee, target_date, user, interval_key):
        """Send a private inbox notification to one Responsible.

        Uses ``message_notify`` (mail.message with
        ``message_type='user_notification'``) instead of ``message_post``:
        - Hidden from the employee's public chatter
          (``mail.thread.message_ids`` excludes ``user_notification``).
        - No follower fan-out — only the partner in ``partner_ids``
          receives the notification.
        - Each Responsible therefore sees ONLY their own per-interval
          notification — never anyone else's.

        **Inbox routing is forced** for every recipient regardless of
        their ``res.users.notification_type`` preference. Without this,
        a user at ``notification_type='email'`` (e.g. ``base.user_admin``)
        would only get the email and never see the message in Discuss
        → Inbox; with this, every Responsible sees it in the Odoo UI.

        The matching rich-template email is sent separately by
        ``_send_birthday_email`` so each Responsible receives exactly
        one email per dispatch. To avoid duplicating that email, the
        ``mail.mail`` row that ``message_notify`` auto-queues for
        email-routed recipients is dropped before it sends.
        """
        label = self._format_birthday_label(target_date, lang=user.lang)
        emp_name = employee.sudo().name
        if interval_key == INTERVAL_ON_DAY:
            body = _(
                "🎉 Today is %(name)s's birthday (%(date)s).",
                name=emp_name,
                date=label,
            )
            subject = _("Birthday today: %(name)s", name=emp_name)
        else:
            when_text = (
                _('in 7 days') if interval_key == INTERVAL_7_DAYS
                else _('tomorrow')
            )
            body = _(
                "🎂 %(name)s has a birthday %(when)s (%(date)s). "
                "Please prepare congratulations.",
                name=emp_name,
                when=when_text,
                date=label,
            )
            subject = _(
                "Upcoming birthday %(when)s: %(name)s",
                when=when_text,
                name=emp_name,
            )
        # mail_notify_force_send=False keeps the auto-queued mail.mail
        # in 'outgoing' state instead of sending it inline. We then
        # unlink it before the email cron picks it up — see comment
        # below for rationale.
        msg = employee.sudo().with_context(
            mail_notify_force_send=False,
        ).message_notify(
            partner_ids=[user.partner_id.id],
            body=body,
            subject=subject,
        )
        self._birthday_force_inbox_routing(msg, user.partner_id)

    @api.model
    def _birthday_force_inbox_routing(self, message, partner):
        """Force the mail.notification for ``partner`` to ``inbox``.

        Drops any auto-queued ``mail.mail`` row tied to ``message`` so
        the user does not receive the bare ``message_notify`` email in
        addition to the rich ``mail.template`` email sent by
        ``_send_birthday_email``.
        """
        notif = self.env['mail.notification'].sudo().search([
            ('mail_message_id', '=', message.id),
            ('res_partner_id', '=', partner.id),
        ])
        if not notif:
            return
        # Drop the bare mail.mail row regardless of state — in dev (no
        # SMTP) it is in 'exception', in prod it would still be
        # 'outgoing' because mail_notify_force_send=False kept it from
        # sending. Either way the rich template email comes via
        # _send_birthday_email so we lose no content.
        self.env['mail.mail'].sudo().search([
            ('mail_message_id', '=', message.id),
        ]).unlink()
        notif.write({
            'notification_type': 'inbox',
            'notification_status': 'sent',
            'is_read': False,
        })

    @api.model
    def _send_birthday_email(self, employee, user, interval_key):
        """Send the per-interval birthday email to one Responsible."""
        xmlid = EMAIL_TEMPLATE_XMLIDS.get(interval_key)
        if not xmlid:
            _logger.warning(
                "Birthday reminders: no email template configured for "
                "interval %s; skipping.", interval_key,
            )
            return
        template = self.env.ref(xmlid, raise_if_not_found=False)
        if not template:
            _logger.warning(
                "Birthday reminders: mail.template %s missing; skipping email.",
                xmlid,
            )
            return
        if not user.email:
            _logger.info(
                "Birthday reminders: user #%s (%s) has no email; skipping.",
                user.id, user.login,
            )
            return
        try:
            template.sudo().with_context(lang=user.lang).send_mail(
                employee.id,
                force_send=True,
                email_values={'email_to': user.email},
            )
        except Exception:
            _logger.exception(
                "Birthday reminders: failed to send email to user #%s "
                "for employee #%s (interval=%s).",
                user.id, employee.id, interval_key,
            )

    # ------------------------------------------------------------------
    # Employee-facing greeting (v17.0.2.15.0)
    # ------------------------------------------------------------------
    @api.model
    def _send_employee_greetings(self, today):
        """Send each today-birthday employee a personal greeting email.

        Independent of subscriptions: still runs when there are zero
        Responsibles configured. Idempotent via the standard log table —
        log rows use base.user_root.id as user_id so the existing UNIQUE
        (employee, date, interval, user_id) constraint covers the
        "system-emitted, one per day" semantic.

        On no-email or send-error the row is still written (with
        greeting_status='failed') and all active Responsibles receive
        a failure broadcast via inbox + email — same dual-channel mix
        as the existing per-interval reminders.
        """
        ICP = self.env['ir.config_parameter'].sudo()
        raw = ICP.get_param(GREETING_ENABLED_PARAM)
        enabled = True if raw is None else str(raw).lower() in ('1', 'true', 'yes')
        if not enabled:
            return

        root = self.env.ref('base.user_root', raise_if_not_found=False)
        if not root:
            _logger.error(
                "Birthday greetings: base.user_root missing; aborting."
            )
            return

        Log = self.env['birthday.reminder.log'].sudo()
        employees = self._employees_with_birthday_on(today)
        if not employees:
            return

        for emp in employees:
            already = Log.search_count([
                ('employee_id', '=', emp.id),
                ('birthday_date', '=', today),
                ('interval', '=', INTERVAL_GREETING),
                ('user_id', '=', root.id),
            ])
            if already:
                continue
            try:
                email_to = self._pick_employee_greeting_email(emp)
                if not email_to:
                    Log.create({
                        'employee_id': emp.id,
                        'user_id': root.id,
                        'birthday_date': today,
                        'interval': INTERVAL_GREETING,
                        'greeting_status': 'failed',
                        'greeting_failure_reason': 'no_email',
                    })
                    self._notify_responsibles_greeting_failed(
                        emp, today, reason='no_email',
                    )
                    continue
                self._send_employee_birthday_email(emp, email_to)
                Log.create({
                    'employee_id': emp.id,
                    'user_id': root.id,
                    'birthday_date': today,
                    'interval': INTERVAL_GREETING,
                    'greeting_status': 'sent',
                })
            except Exception:
                _logger.exception(
                    "Birthday greeting: send failed for employee #%s.",
                    emp.id,
                )
                # Even if Log/notify themselves throw, we must not let
                # one bad employee block the rest of the loop.
                try:
                    Log.create({
                        'employee_id': emp.id,
                        'user_id': root.id,
                        'birthday_date': today,
                        'interval': INTERVAL_GREETING,
                        'greeting_status': 'failed',
                        'greeting_failure_reason': 'send_error',
                    })
                    self._notify_responsibles_greeting_failed(
                        emp, today, reason='send_error',
                    )
                except Exception:
                    _logger.exception(
                        "Birthday greeting: also failed to log/notify "
                        "the send_error for employee #%s.", emp.id,
                    )

    @api.model
    def _pick_employee_greeting_email(self, employee):
        """Pick the greeting recipient address: work_email → private_email.

        sudo() is required because private_email is gated by
        hr.group_hr_user; the cron itself runs as root but helpers may
        be invoked from less privileged contexts in the future.
        """
        emp_su = employee.sudo()
        work = (emp_su.work_email or '').strip()
        if work:
            return work
        private = (emp_su.private_email or '').strip()
        if private:
            return private
        return None

    @api.model
    def _send_employee_birthday_email(self, employee, email_to):
        """Render and send the personal greeting template.

        Raises on failure so the caller can log greeting_status='failed'
        with the right reason and broadcast a notification to all
        Responsibles. The choice of language goes employee.user.lang →
        employee.company.partner.lang → 'en_US' so the message is in
        the most-relevant locale even when the employee has no linked
        res.users.
        """
        template = self.env.ref(
            EMAIL_TEMPLATE_XMLIDS[INTERVAL_GREETING],
            raise_if_not_found=False,
        )
        if not template:
            raise UserError(_("Greeting template missing."))
        emp_su = employee.sudo()
        user_lang = (
            (emp_su.user_id.lang if emp_su.user_id else None)
            or (emp_su.company_id.partner_id.lang if emp_su.company_id else None)
            or 'en_US'
        )
        template.sudo().with_context(lang=user_lang).send_mail(
            employee.id,
            force_send=True,
            raise_exception=True,
            email_values={'email_to': email_to},
        )

    @api.model
    def _notify_responsibles_greeting_failed(self, employee, today, reason):
        """Broadcast a failure notice to every active Responsible.

        Two channels per recipient — private inbox notification (via
        message_notify + forced inbox routing) and a templated email
        sent through mail_template_birthday_greeting_failed. Same channel
        mix as the existing per-interval reminders, so the failure
        notification is consistent with what Responsibles already see.

        Errors per recipient are caught and logged so one bad address
        does not block the rest of the broadcast.
        """
        Sub = self.env['birthday.reminder.subscription'].sudo()
        active_subs = Sub.search([('active', '=', True)])
        if not active_subs:
            return
        template = self.env.ref(
            GREETING_FAILED_TEMPLATE_XMLID, raise_if_not_found=False,
        )
        emp_name = employee.sudo().name
        label = self._format_birthday_label(today)
        reason_text = (
            _("no email address on record")
            if reason == 'no_email'
            else _("email delivery error")
        )
        body = _(
            "⚠️ Could not send the birthday greeting to %(name)s today "
            "(%(date)s). Reason: %(reason)s. Please reach out personally.",
            name=emp_name, date=label, reason=reason_text,
        )
        subject = _(
            "Birthday greeting FAILED: %(name)s", name=emp_name,
        )
        for sub in active_subs:
            user = sub.user_id
            try:
                msg = employee.sudo().with_context(
                    mail_notify_force_send=False,
                ).message_notify(
                    partner_ids=[user.partner_id.id],
                    body=body,
                    subject=subject,
                )
                self._birthday_force_inbox_routing(msg, user.partner_id)
                if template and user.email:
                    template.sudo().with_context(
                        lang=user.lang,
                    ).send_mail(
                        employee.id,
                        force_send=True,
                        email_values={
                            'email_to': user.email,
                            'subject': subject,
                        },
                    )
            except Exception:
                _logger.exception(
                    "Birthday greeting-failure notify failed for user "
                    "#%s, employee #%s.", user.id, employee.id,
                )

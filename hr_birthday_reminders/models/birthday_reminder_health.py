import logging
from datetime import datetime, timedelta

import pytz

from odoo import _, api, fields, models


_logger = logging.getLogger(__name__)


# Cron status thresholds, expressed in hours since ``ir.cron.lastcall``.
# 24h is the notification period (daily cron). Slack of 2h covers normal
# scheduler drift — Odoo's cron scheduler does not fire on the exact
# configured-hour boundary. Past the warning ceiling we know at least one
# daily cycle was missed.
CRON_AGE_OK_HOURS = 26
CRON_AGE_WARNING_HOURS = 30

# Side-check: if ``ir.cron.nextcall`` is more than this many hours in the
# past, the scheduler itself is stuck regardless of when it last fired.
CRON_NEXTCALL_OVERDUE_HOURS = 2

REMINDERS_CRON_XMLID = 'hr_birthday_reminders.ir_cron_birthday_reminders'
GREETINGS_CRON_XMLID = 'hr_birthday_reminders.ir_cron_birthday_greetings'

# Reminder intervals that count as "reminders to Responsibles" — i.e.
# everything except the personal greeting to the employee themselves.
REMINDER_INTERVALS = ('7_days', '1_day', 'on_day')

# Window (in days) for the "recent failures" counter on the dashboard.
RECENT_FAILURES_WINDOW_DAYS = 30


STATUS_SELECTION = [
    ('ok', 'OK'),
    ('warning', 'Warning'),
    ('danger', 'Danger'),
]


class BirthdayReminderHealth(models.TransientModel):
    """Single-record snapshot of the module's operational health.

    The dashboard is a read-only viewer. Each time a user opens the
    Health Check menu, ``action_open_dashboard`` creates a fresh
    transient record and routes the user to its form view; every
    computed field is re-queried from ``ir.cron``, the reminders log
    and the subscriptions table, so what the user sees always
    reflects "right now".

    No persistent schema → no migration, no auto-vacuum concerns
    beyond the standard ``_transient_max_hours``. The record is a
    pure facade over existing data.
    """

    _name = 'birthday.reminder.health'
    _description = 'Birthday Reminders Health Check'
    _transient_max_hours = 1

    # ------------------------------------------------------------------
    # Reminders cron
    # ------------------------------------------------------------------
    reminders_cron_active = fields.Boolean(
        string='Reminders cron enabled',
        compute='_compute_reminders_cron',
    )
    reminders_cron_lastcall = fields.Datetime(
        string='Reminders cron last run',
        compute='_compute_reminders_cron',
    )
    reminders_cron_nextcall = fields.Datetime(
        string='Reminders cron next run',
        compute='_compute_reminders_cron',
    )
    reminders_cron_status = fields.Selection(
        selection=STATUS_SELECTION,
        string='Reminders cron status',
        compute='_compute_reminders_cron',
    )

    # ------------------------------------------------------------------
    # Greetings cron
    # ------------------------------------------------------------------
    greetings_cron_active = fields.Boolean(
        string='Greetings cron enabled',
        compute='_compute_greetings_cron',
    )
    greetings_cron_lastcall = fields.Datetime(
        string='Greetings cron last run',
        compute='_compute_greetings_cron',
    )
    greetings_cron_nextcall = fields.Datetime(
        string='Greetings cron next run',
        compute='_compute_greetings_cron',
    )
    greetings_cron_status = fields.Selection(
        selection=STATUS_SELECTION,
        string='Greetings cron status',
        compute='_compute_greetings_cron',
    )

    # ------------------------------------------------------------------
    # Today's activity
    # ------------------------------------------------------------------
    today_birthdays = fields.Integer(
        string='Birthdays today',
        compute='_compute_today_activity',
        help="Number of active employees whose birthday matches today "
             "(in the current user's timezone).",
    )
    today_reminders_sent = fields.Integer(
        string='Reminders sent today',
        compute='_compute_today_activity',
        help="Log rows for the three Responsible-facing intervals "
             "(7-days, 1-day, on-day) created today.",
    )
    today_greetings_sent = fields.Integer(
        string='Greetings sent today',
        compute='_compute_today_activity',
    )
    today_greetings_failed = fields.Integer(
        string='Greetings failed today',
        compute='_compute_today_activity',
    )

    # ------------------------------------------------------------------
    # Subscriptions
    # ------------------------------------------------------------------
    subscriptions_active = fields.Integer(
        string='Active subscriptions',
        compute='_compute_subscriptions',
    )
    subscriptions_stale = fields.Integer(
        string='Stale subscriptions',
        compute='_compute_subscriptions',
        help="Active subscriptions whose last_run_date is not today in "
             "the subscribed user's own timezone. Indicates the cron "
             "did not process them in their local day.",
    )

    # ------------------------------------------------------------------
    # Recent failures
    # ------------------------------------------------------------------
    recent_failures_30d = fields.Integer(
        string='Failed greetings (30d)',
        compute='_compute_recent_failures',
    )

    # ------------------------------------------------------------------
    # Overall
    # ------------------------------------------------------------------
    overall_status = fields.Selection(
        selection=STATUS_SELECTION,
        string='Overall status',
        compute='_compute_overall',
    )
    overall_message = fields.Char(
        string='Summary',
        compute='_compute_overall',
    )

    # ==================================================================
    # Computes
    # ==================================================================
    def _compute_reminders_cron(self):
        for rec in self:
            rec._populate_cron_fields(
                xmlid=REMINDERS_CRON_XMLID,
                active_field='reminders_cron_active',
                lastcall_field='reminders_cron_lastcall',
                nextcall_field='reminders_cron_nextcall',
                status_field='reminders_cron_status',
            )

    def _compute_greetings_cron(self):
        for rec in self:
            rec._populate_cron_fields(
                xmlid=GREETINGS_CRON_XMLID,
                active_field='greetings_cron_active',
                lastcall_field='greetings_cron_lastcall',
                nextcall_field='greetings_cron_nextcall',
                status_field='greetings_cron_status',
            )

    def _populate_cron_fields(self, xmlid, active_field, lastcall_field,
                              nextcall_field, status_field):
        cron = self.env.ref(xmlid, raise_if_not_found=False)
        if not cron:
            self[active_field] = False
            self[lastcall_field] = False
            self[nextcall_field] = False
            self[status_field] = 'danger'
            return
        # ir.cron is restricted to base.group_system, so Birthday Responsibles
        # cannot read it directly even though they can view this dashboard.
        # Promote to sudo for the status-display read only — does not grant
        # write access elsewhere.
        cron = cron.sudo()
        self[active_field] = cron.active
        self[lastcall_field] = cron.lastcall
        self[nextcall_field] = cron.nextcall
        self[status_field] = self._classify_cron_status(
            active=cron.active,
            lastcall=cron.lastcall,
            nextcall=cron.nextcall,
        )

    @api.model
    def _classify_cron_status(self, active, lastcall, nextcall):
        """Map cron state to ``ok`` / ``warning`` / ``danger``.

        Thresholds (per plan):
        - disabled or never-ran  → danger
        - lastcall age <= 26h    → ok
        - lastcall age <= 30h    → warning
        - lastcall age > 30h     → danger
        - nextcall > 2h in past  → danger (scheduler stuck)
        """
        if not active:
            return 'danger'
        if not lastcall:
            return 'danger'
        now = fields.Datetime.now()
        age = now - lastcall
        # Compare hours via total_seconds for sub-hour precision.
        age_hours = age.total_seconds() / 3600.0
        if age_hours > CRON_AGE_WARNING_HOURS:
            return 'danger'
        if nextcall and (now - nextcall) > timedelta(
            hours=CRON_NEXTCALL_OVERDUE_HOURS
        ):
            return 'danger'
        if age_hours > CRON_AGE_OK_HOURS:
            return 'warning'
        return 'ok'

    def _compute_today_activity(self):
        Log = self.env['birthday.reminder.log'].sudo()
        Employee = self.env['hr.employee'].sudo()
        today = fields.Date.context_today(self)
        # ``notified_at`` is a Datetime. Filter to today via the
        # context-aware lower bound; the upper bound is implicit.
        day_start = fields.Datetime.to_string(
            datetime.combine(today, datetime.min.time())
        )
        for rec in self:
            rec.today_birthdays = len(
                Employee._employees_with_birthday_on(today)
            )
            rec.today_reminders_sent = Log.search_count([
                ('interval', 'in', REMINDER_INTERVALS),
                ('notified_at', '>=', day_start),
            ])
            rec.today_greetings_sent = Log.search_count([
                ('interval', '=', 'greeting'),
                ('greeting_status', '=', 'sent'),
                ('notified_at', '>=', day_start),
            ])
            rec.today_greetings_failed = Log.search_count([
                ('interval', '=', 'greeting'),
                ('greeting_status', '=', 'failed'),
                ('notified_at', '>=', day_start),
            ])

    def _compute_subscriptions(self):
        Sub = self.env['birthday.reminder.subscription'].sudo()
        for rec in self:
            active_subs = Sub.search([('active', '=', True)])
            rec.subscriptions_active = len(active_subs)
            rec.subscriptions_stale = sum(
                1 for s in active_subs if rec._subscription_is_stale(s)
            )

    @api.model
    def _subscription_is_stale(self, subscription):
        """Replicate the cron's per-user "today already processed" check.

        Returns True when ``last_run_date`` is not today in the
        subscribed user's own timezone (matches the cron logic in
        ``hr.employee._birthday_maybe_run_for_subscription``).
        """
        tz_name = subscription.user_id.tz or 'UTC'
        try:
            user_tz = pytz.timezone(tz_name)
        except pytz.UnknownTimeZoneError:
            user_tz = pytz.UTC
        now_utc = pytz.UTC.localize(fields.Datetime.now())
        local_today = now_utc.astimezone(user_tz).date()
        return subscription.last_run_date != local_today

    def _compute_recent_failures(self):
        Log = self.env['birthday.reminder.log'].sudo()
        cutoff = fields.Date.context_today(self) - timedelta(
            days=RECENT_FAILURES_WINDOW_DAYS
        )
        cutoff_dt = fields.Datetime.to_string(
            datetime.combine(cutoff, datetime.min.time())
        )
        for rec in self:
            rec.recent_failures_30d = Log.search_count([
                ('interval', '=', 'greeting'),
                ('greeting_status', '=', 'failed'),
                ('notified_at', '>=', cutoff_dt),
            ])

    @api.depends(
        'reminders_cron_status',
        'greetings_cron_status',
        'today_greetings_failed',
        'subscriptions_stale',
    )
    def _compute_overall(self):
        rank = {'ok': 0, 'warning': 1, 'danger': 2}
        inv_rank = {v: k for k, v in rank.items()}
        for rec in self:
            cron_statuses = [
                rec.reminders_cron_status or 'danger',
                rec.greetings_cron_status or 'danger',
            ]
            worst_rank = max(rank[s] for s in cron_statuses)
            if rec.today_greetings_failed > 0:
                worst_rank = max(worst_rank, rank['danger'])
            if rec.subscriptions_stale > 0:
                # Stale = warning, not danger — a single missed run is
                # recoverable on the next cron tick.
                worst_rank = max(worst_rank, rank['warning'])
            rec.overall_status = inv_rank[worst_rank]
            rec.overall_message = rec._build_overall_message(rec.overall_status)

    def _build_overall_message(self, status):
        if status == 'ok':
            return _(
                "All systems healthy. Both crons ran in the last 26 "
                "hours and no greeting failures recorded today."
            )
        problems = []
        if self.reminders_cron_status != 'ok':
            problems.append(_(
                "Reminders cron is %(s)s", s=dict(STATUS_SELECTION).get(
                    self.reminders_cron_status, self.reminders_cron_status,
                ),
            ))
        if self.greetings_cron_status != 'ok':
            problems.append(_(
                "Greetings cron is %(s)s", s=dict(STATUS_SELECTION).get(
                    self.greetings_cron_status, self.greetings_cron_status,
                ),
            ))
        if self.today_greetings_failed:
            problems.append(_(
                "%(n)s greeting(s) failed today", n=self.today_greetings_failed,
            ))
        if self.subscriptions_stale:
            problems.append(_(
                "%(n)s subscription(s) not processed today",
                n=self.subscriptions_stale,
            ))
        if not problems:
            # Defensive — overall_status came back non-ok but no
            # individual signal looked bad. Should not happen, but
            # produce something readable instead of an empty string.
            return _("Status is %(s)s — check individual signals below.",
                     s=status)
        return "; ".join(problems)

    # ==================================================================
    # Actions
    # ==================================================================
    @api.model
    def action_open_dashboard(self):
        """Entry point from the menu — open a fresh record's form view."""
        rec = self.create({})
        return {
            'type': 'ir.actions.act_window',
            'name': _('Birthday Reminders — Health Check'),
            'res_model': self._name,
            'view_mode': 'form',
            'res_id': rec.id,
            'target': 'current',
        }

    def action_refresh(self):
        """Re-open the dashboard with a fresh record.

        TransientModel computed fields are lazy; re-opening drops the
        current record and creates a new one, which re-runs every
        compute against the latest data.
        """
        self.ensure_one()
        return self.action_open_dashboard()

    def action_run_reminders_cron_now(self):
        """Manager-only: trigger the reminders cron synchronously.

        Safe by design — the underlying flow is idempotent via the
        ``birthday.reminder.log`` UNIQUE constraint, so a manual
        re-run on the same day produces zero new notifications.
        """
        self.ensure_one()
        self.env['hr.employee'].sudo()._cron_birthday_reminders()
        return self.action_refresh()

    def action_run_greetings_cron_now(self):
        self.ensure_one()
        self.env['hr.employee'].sudo()._cron_birthday_greetings_to_employees()
        return self.action_refresh()

    def action_open_failed_greetings(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Failed Greetings (last 30 days)'),
            'res_model': 'birthday.reminder.log',
            'view_mode': 'tree,form',
            'domain': [
                ('interval', '=', 'greeting'),
                ('greeting_status', '=', 'failed'),
                ('notified_at', '>=', fields.Datetime.to_string(
                    datetime.combine(
                        fields.Date.context_today(self) - timedelta(
                            days=RECENT_FAILURES_WINDOW_DAYS
                        ),
                        datetime.min.time(),
                    )
                )),
            ],
            'target': 'current',
        }

    def action_open_stale_subscriptions(self):
        self.ensure_one()
        Sub = self.env['birthday.reminder.subscription'].sudo()
        active_subs = Sub.search([('active', '=', True)])
        stale_ids = [
            s.id for s in active_subs if self._subscription_is_stale(s)
        ]
        return {
            'type': 'ir.actions.act_window',
            'name': _('Stale Subscriptions'),
            'res_model': 'birthday.reminder.subscription',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', stale_ids)],
            'target': 'current',
        }

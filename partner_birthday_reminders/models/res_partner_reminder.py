import logging
from datetime import timedelta

import pytz

from odoo import _, api, fields, models
from odoo.tools.misc import format_date

from .constants import (
    ACTIVITY_SUMMARY_PREFIX,
    EMAIL_TEMPLATE_XMLIDS,
    INTERVAL_1_DAY,
    INTERVAL_7_DAYS,
    INTERVAL_OFFSETS,
    INTERVAL_ON_DAY,
    TODO_ACTIVITY_XMLID,
)

_logger = logging.getLogger(__name__)


class ResPartnerBirthdayReminder(models.Model):
    """Cron and notification dispatch for contact birthdays.

    Second half of the ``res.partner`` extension — the field/compute
    layer lives in ``res_partner.py``. Split purely for readability;
    both classes extend the same model.

    Audience model, and the one structural difference from
    ``hr_birthday_reminders``: there is **no roster**. Each reminder
    goes to exactly one person — the contact's Account Manager
    (``res.partner.user_id``). ``partner.birthday.pref`` only stores
    that user's interval choices and their per-local-day run stamp.

    Channels per interval, all gated by ``partner.birthday.log``:

    ============  =========================================================
    7 days        To Do activity (deadline = birthday) + inbox note + email
    1 day         To Do activity (deadline = birthday) + inbox note + email
    On the day    inbox note + email (nothing left to prepare → no To Do)
    ============  =========================================================

    Nothing is ever emailed to the contact themselves: the module is a
    private nudge to the Account Manager, who decides how to greet their
    client.
    """

    _inherit = 'res.partner'

    # ------------------------------------------------------------------
    # Cron entry point
    # ------------------------------------------------------------------
    @api.model
    def _cron_partner_birthday_reminders(self):
        """Daily entry point, fired at the configured UTC hour.

        Order matters:

        1. expired To Dos are cleared before new ones are created, so the
           Account Manager's dashboard only shows what is still
           actionable;
        2. the stored helpers (and thus eligibility) are refreshed
           against the current day;
        3. preference rows are provisioned for anyone who has become an
           Account Manager since the last run;
        4. each active preference row is processed once per its user's
           local day.

        Every step is individually guarded: one broken contact, user or
        preference row must never stop the rest of the batch.
        """
        self._cleanup_overdue_birthday_activities()
        self._refresh_partner_birthday_helpers()

        Pref = self.env['partner.birthday.pref'].sudo()
        managers = self._birthday_account_managers()
        try:
            Pref._ensure_prefs_for_users(managers)
        except Exception:
            _logger.exception(
                "Contact birthday reminders: failed provisioning "
                "preference rows; continuing with existing ones.",
            )

        for pref in Pref.search([('active', '=', True)]):
            try:
                self._birthday_maybe_run_for_pref(pref)
            except Exception:
                _logger.exception(
                    "Contact birthday reminders: failed processing "
                    "preferences #%s (user=%s).", pref.id, pref.user_id.id,
                )

    @api.model
    def _birthday_account_managers(self):
        """Internal users who are Account Manager of ≥1 eligible contact."""
        partners = self.sudo().search([
            ('birthday_eligible', '=', True),
            ('user_id', '!=', False),
        ])
        return partners.mapped('user_id').filtered(
            lambda u: u.active and not u.share
        )

    @api.model
    def _cleanup_overdue_birthday_activities(self):
        """Delete our own To Dos whose deadline has arrived or passed.

        The deadline is the birthday itself: once it is today, the
        on-day notification takes over and the activity is pure noise on
        the Account Manager's dashboard. Matching is restricted to the
        summary prefix this module writes, so activities created by
        anyone else on the same contact are never touched.

        Caveat inherited by design: the prefix is English. In a
        multi-language deployment where the cron user's language differs,
        switch to a dedicated ``mail.activity.type`` instead of a summary
        match.
        """
        today = fields.Date.context_today(self.env.user)
        overdue = self.env['mail.activity'].sudo().search([
            ('res_model', '=', 'res.partner'),
            ('summary', 'ilike', '%s%%' % ACTIVITY_SUMMARY_PREFIX),
            ('date_deadline', '<=', today),
        ])
        if overdue:
            _logger.info(
                "Contact birthday reminders: deleting %d expired "
                "activity/ies (deadline <= %s).", len(overdue), today,
            )
            overdue.unlink()

    # ------------------------------------------------------------------
    # Per-user orchestration
    # ------------------------------------------------------------------
    @api.model
    def _birthday_maybe_run_for_pref(self, pref):
        """Run the enabled intervals for one user, in that user's timezone.

        ``last_run_date`` is keyed on the user's *local* date, so a
        manual re-run the same day is a no-op and the daily guarantee
        holds even when the fixed UTC firing straddles local midnight.
        """
        tz_name = pref.user_id.tz or 'UTC'
        try:
            user_tz = pytz.timezone(tz_name)
        except pytz.UnknownTimeZoneError:
            _logger.warning(
                "Contact birthday reminders: preferences #%s has unknown "
                "tz '%s'; falling back to UTC.", pref.id, tz_name,
            )
            user_tz = pytz.UTC

        now_local = pytz.UTC.localize(fields.Datetime.now()).astimezone(user_tz)
        local_today = now_local.date()
        if pref.last_run_date == local_today:
            return

        self._birthday_process_pref(pref, local_today)
        pref.sudo().write({'last_run_date': local_today})

    @api.model
    def _birthday_process_pref(self, pref, today):
        """Dispatch every interval this user has enabled."""
        enabled = {
            INTERVAL_7_DAYS: pref.notify_7_days_before,
            INTERVAL_1_DAY: pref.notify_1_day_before,
            INTERVAL_ON_DAY: pref.notify_on_day,
        }
        for interval_key, is_on in enabled.items():
            if not is_on:
                continue
            target_date = today + timedelta(days=INTERVAL_OFFSETS[interval_key])
            self._process_partner_birthday_interval(
                target_date, interval_key, pref.user_id,
            )

    @api.model
    def _process_partner_birthday_interval(self, target_date, interval_key, user):
        """Notify ``user`` about their contacts born on ``target_date``.

        Only contacts whose Account Manager *is* this user are
        considered — that filter is the whole audience model. The log
        table gates each ``(partner, date, interval, user)`` combination;
        its UNIQUE constraint is what makes concurrent or repeated runs
        safe, the pre-check merely avoids pointless work.
        """
        partners = self._partners_with_birthday_on(target_date).filtered(
            lambda p: p.user_id.id == user.id
        )
        if not partners:
            return
        Log = self.env['partner.birthday.log'].sudo()
        for partner in partners:
            already = Log.search_count([
                ('partner_id', '=', partner.id),
                ('birthday_date', '=', target_date),
                ('interval', '=', interval_key),
                ('user_id', '=', user.id),
            ])
            if already:
                continue
            try:
                if interval_key in (INTERVAL_7_DAYS, INTERVAL_1_DAY):
                    self._schedule_partner_birthday_activity(
                        partner, target_date, interval_key, user,
                    )
                self._notify_partner_birthday_user(
                    partner, target_date, user, interval_key,
                )
                self._send_partner_birthday_email(partner, user, interval_key)
                Log.create({
                    'partner_id': partner.id,
                    'user_id': user.id,
                    'birthday_date': target_date,
                    'interval': interval_key,
                })
            except Exception:
                _logger.exception(
                    "Contact birthday reminders: failed (partner=%s "
                    "user=%s interval=%s date=%s).",
                    partner.id, user.id, interval_key, target_date,
                )

    # ------------------------------------------------------------------
    # Channels
    # ------------------------------------------------------------------
    @api.model
    def _format_birthday_label(self, target_date, lang=None):
        """Localised 'dd MMMM' label — never the year (no age disclosure)."""
        return format_date(
            self.env, target_date, date_format='dd MMMM', lang_code=lang,
        )

    @api.model
    def _birthday_when_text(self, interval_key):
        if interval_key == INTERVAL_7_DAYS:
            return _('in 7 days')
        if interval_key == INTERVAL_1_DAY:
            return _('tomorrow')
        return _('today')

    @api.model
    def _schedule_partner_birthday_activity(self, partner, target_date,
                                            interval_key, user):
        """Create one To Do on the contact, assigned to its Account Manager.

        ``mail_activity_quick_update=True`` suppresses Odoo's stock
        "<record>: <summary> assigned to you" auto-notification
        (``mail/models/mail_activity.py``). We send our own friendlier
        notification right after, so the system one would be a duplicate
        — and an inconsistent one, since it follows each user's
        ``notification_type`` while ours is always in the inbox.
        """
        when_text = self._birthday_when_text(interval_key)
        label = self._format_birthday_label(target_date, lang=user.lang)
        note = _(
            "🎂 %(name)s has a birthday %(when)s (%(date)s). "
            "A good moment to reach out.",
            name=partner.display_name,
            when=when_text,
            date=label,
        )
        partner.sudo().with_context(
            mail_activity_quick_update=True,
        ).activity_schedule(
            TODO_ACTIVITY_XMLID,
            date_deadline=target_date,
            summary=_(
                "%(prefix)s: %(name)s",
                prefix=ACTIVITY_SUMMARY_PREFIX,
                name=partner.display_name,
            ),
            note=note,
            user_id=user.id,
        )

    @api.model
    def _notify_partner_birthday_user(self, partner, target_date, user,
                                      interval_key):
        """Send a private inbox note to the Account Manager.

        ``message_notify`` rather than ``message_post``, for two reasons
        that matter more here than they did for employees:

        * a contact's chatter is customer-facing context shared with the
          whole sales team — internal birthday chatter does not belong
          there. ``mail.thread.message_ids`` excludes
          ``user_notification`` messages, so nothing shows up on the
          record;
        * ``message_notify`` does no follower fan-out, so only the
          Account Manager is told — not every follower of the contact.

        Inbox routing is then forced, so the note is visible in Discuss
        even for users whose ``notification_type`` is ``email``; the
        bare auto-queued ``mail.mail`` is dropped because the rich
        templated email is sent separately.
        """
        label = self._format_birthday_label(target_date, lang=user.lang)
        name = partner.display_name
        when_text = self._birthday_when_text(interval_key)
        if interval_key == INTERVAL_ON_DAY:
            body = _(
                "🎉 Today is %(name)s's birthday (%(date)s).",
                name=name, date=label,
            )
            subject = _("Contact birthday today: %(name)s", name=name)
        else:
            body = _(
                "🎂 %(name)s has a birthday %(when)s (%(date)s). "
                "A good moment to reach out.",
                name=name, when=when_text, date=label,
            )
            subject = _(
                "Upcoming contact birthday %(when)s: %(name)s",
                when=when_text, name=name,
            )
        message = partner.sudo().with_context(
            mail_notify_force_send=False,
        ).message_notify(
            partner_ids=[user.partner_id.id],
            body=body,
            subject=subject,
        )
        self._birthday_force_inbox_routing(message, user.partner_id)

    @api.model
    def _birthday_force_inbox_routing(self, message, partner):
        """Pin the notification to the inbox and drop the bare email.

        Without this, a user at ``notification_type='email'`` would only
        ever get email and never see the note in Discuss. The
        auto-queued ``mail.mail`` is unlinked in any state ('outgoing'
        in production thanks to ``mail_notify_force_send=False``,
        'exception' on a dev box without SMTP) — no content is lost,
        the templated email carries it.
        """
        notification = self.env['mail.notification'].sudo().search([
            ('mail_message_id', '=', message.id),
            ('res_partner_id', '=', partner.id),
        ])
        if not notification:
            return
        self.env['mail.mail'].sudo().search([
            ('mail_message_id', '=', message.id),
        ]).unlink()
        notification.write({
            'notification_type': 'inbox',
            'notification_status': 'sent',
            'is_read': False,
        })

    @api.model
    def _send_partner_birthday_email(self, partner, user, interval_key):
        """Send the per-interval email to the Account Manager."""
        xmlid = EMAIL_TEMPLATE_XMLIDS.get(interval_key)
        template = self.env.ref(xmlid, raise_if_not_found=False) if xmlid else None
        if not template:
            _logger.warning(
                "Contact birthday reminders: mail.template %s missing; "
                "skipping email.", xmlid,
            )
            return
        if not user.email:
            _logger.info(
                "Contact birthday reminders: user #%s (%s) has no email; "
                "skipping email.", user.id, user.login,
            )
            return
        try:
            template.sudo().with_context(lang=user.lang).send_mail(
                partner.id,
                force_send=True,
                email_values={'email_to': user.email},
            )
        except Exception:
            _logger.exception(
                "Contact birthday reminders: failed sending email to "
                "user #%s for contact #%s (interval=%s).",
                user.id, partner.id, interval_key,
            )

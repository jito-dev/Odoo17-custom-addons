from datetime import timedelta
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


CRON_HOUR_PARAM = 'hr_birthday_reminders.cron_hour_utc'
CRON_XMLID = 'hr_birthday_reminders.ir_cron_birthday_reminders'
DEFAULT_HOUR = 6

GREETING_ENABLED_PARAM = 'hr_birthday_reminders.greeting_enabled'

# v17.0.2.16.0 — separate hour for the employee-greeting cron.
GREETING_HOUR_PARAM = 'hr_birthday_reminders.greeting_hour_utc'
GREETING_CRON_XMLID = 'hr_birthday_reminders.ir_cron_birthday_greetings'
DEFAULT_GREETING_HOUR = 6

# v17.0.2.17.0 — custom banner image for the greeting email.
# Stored base64-encoded inside ir.config_parameter.value (a text column),
# so a single image is shared across renders without an attachment row.
GREETING_BANNER_PARAM = 'hr_birthday_reminders.greeting_banner_b64'
GREETING_TEMPLATE_XMLID = (
    'hr_birthday_reminders.mail_template_birthday_to_employee'
)

# v17.0.2.30.0 — health watchdog / alerting knobs.
ALERT_ENABLED_PARAM = 'hr_birthday_reminders.alert_enabled'
ALERT_REPEAT_HOURS_PARAM = 'hr_birthday_reminders.alert_repeat_hours'
DEFAULT_ALERT_REPEAT_HOURS = 24


class ResConfigSettings(models.TransientModel):
    """Settings for the daily birthday-reminders cron.

    Two knobs:

    - ``birthday_reminders_enabled`` mirrors ``ir.cron.active`` for the
      birthday cron record. Source of truth lives on the cron itself —
      we read it via the ``default`` callable and write it back through
      ``set_values``. This keeps the toggle and the Scheduled Action
      perfectly in sync without a second persistence layer to maintain.

    - ``birthday_reminder_hour_utc`` persists via ``ir.config_parameter``
      (the standard ``config_parameter=`` machinery on the field). The
      ``set_values`` override copies it into the cron record's
      ``nextcall`` only when the hour has actually changed, so saving
      the page repeatedly does not push the next firing further into
      the future.
    """

    _inherit = 'res.config.settings'

    birthday_reminders_enabled = fields.Boolean(
        string='Enable daily birthday reminders',
        default=lambda self: self._default_birthday_reminders_enabled(),
        help="Master switch for the daily cron. Mirrors the 'Active' "
             "flag of the Scheduled Action — toggling here is identical "
             "to toggling it from Technical → Scheduled Actions, but "
             "lives next to the hour setting for convenience. "
             "Disabling does not lose the configured hour.",
    )
    birthday_reminder_hour_utc = fields.Integer(
        string='Birthday reminders hour (UTC)',
        default=DEFAULT_HOUR,
        config_parameter=CRON_HOUR_PARAM,
        help="Hour of day (0-23) in UTC at which the daily birthday-"
             "reminders cron fires. Default 6 (≈ 09:00 Kyiv). "
             "Notifications arrive at varying local wall-clock times "
             "for Responsibles in different timezones — pick an hour "
             "that lands in early-morning for the dominant timezone.",
    )
    birthday_greeting_to_employee_enabled = fields.Boolean(
        string='Send greeting email to employees',
        default=lambda self: self._default_birthday_greeting_enabled(),
        config_parameter=GREETING_ENABLED_PARAM,
        help="When enabled, the daily cron emails a personal birthday "
             "greeting to each employee on their birthday — work_email "
             "first, falling back to private_email. If both are missing "
             "(or the SMTP delivery fails), every active Responsible "
             "receives a failure notification via inbox + email.",
    )
    birthday_greeting_hour_utc = fields.Integer(
        string='Greeting hour (UTC)',
        default=DEFAULT_GREETING_HOUR,
        config_parameter=GREETING_HOUR_PARAM,
        help="Hour 0-23 (UTC) at which the daily employee greeting "
             "cron fires. Independent of the per-Responsible reminders "
             "hour above — set the two to the same value if you want "
             "them to fire in one batch (the v17.0.2.15.0 behaviour). "
             "Default 6 ≈ 09:00 Kyiv.",
    )
    # v17.0.2.17.0 — Binary banner stored as base64 in ir.config_parameter.
    # Cannot use ``config_parameter=`` for Binary; persistence is handled
    # explicitly in get_values / set_values. Leaving the field empty
    # makes the greeting template fall back to res.company.logo.
    birthday_greeting_banner = fields.Binary(
        string='Greeting banner image',
        help="Optional. Replaces the company logo at the top of the "
             "birthday greeting email sent to the employee. If empty, "
             "the email falls back to your company's logo "
             "(res.company.logo). Recommended size: 600×80 px, "
             "PNG or JPG, under 100 KB.",
    )
    # v17.0.2.30.0 — alerting knobs.
    birthday_alert_enabled = fields.Boolean(
        string='Enable health alerts',
        default=lambda self: self._default_birthday_alert_enabled(),
        config_parameter=ALERT_ENABLED_PARAM,
        help="When enabled, the health watchdog cron emails system "
             "admins + Birthday Reminders Managers when the Health "
             "Dashboard turns red. Disable to silence alerts (the "
             "Dashboard remains available either way).",
    )
    birthday_alert_repeat_hours = fields.Integer(
        string='Repeat alert every N hours',
        default=DEFAULT_ALERT_REPEAT_HOURS,
        config_parameter=ALERT_REPEAT_HOURS_PARAM,
        help="If health stays red across multiple watchdog ticks, "
             "re-send the alert after this many hours so the issue "
             "is not forgotten. Default 24.",
    )

    @api.model
    def _default_birthday_reminders_enabled(self):
        cron = self.env.ref(CRON_XMLID, raise_if_not_found=False)
        return bool(cron.sudo().active) if cron else True

    @api.model
    def _default_birthday_greeting_enabled(self):
        """Default the greeting toggle to ON when ICP key is absent.

        Boolean fields normally default to False, but this feature
        is meant to be on out of the box — admins can opt out
        explicitly via the settings page.

        Note: ``get_param`` returns ``False`` (Python bool) when the
        key is absent, not ``None``. Use truthiness check.
        """
        val = self.env['ir.config_parameter'].sudo().get_param(
            GREETING_ENABLED_PARAM,
        )
        if not val:
            return True
        return str(val).lower() in ('1', 'true', 'yes')

    @api.model
    def _default_birthday_alert_enabled(self):
        """Default health alerts ON when ICP key is absent."""
        val = self.env['ir.config_parameter'].sudo().get_param(
            ALERT_ENABLED_PARAM,
        )
        if not val:
            return True
        return str(val).lower() in ('1', 'true', 'yes')

    @api.constrains('birthday_reminder_hour_utc')
    def _check_birthday_reminder_hour_utc(self):
        for s in self:
            if not (0 <= s.birthday_reminder_hour_utc <= 23):
                raise ValidationError(_(
                    "Birthday reminders hour must be between 0 and 23 "
                    "(got %s).",
                    s.birthday_reminder_hour_utc,
                ))

    @api.constrains('birthday_greeting_hour_utc')
    def _check_birthday_greeting_hour_utc(self):
        for s in self:
            if not (0 <= s.birthday_greeting_hour_utc <= 23):
                raise ValidationError(_(
                    "Greeting hour must be between 0 and 23 (got %s).",
                    s.birthday_greeting_hour_utc,
                ))

    @api.model
    def get_values(self):
        """Hydrate the form with values that aren't covered by
        ``config_parameter=`` automation — currently just the banner
        Binary, which we persist as a base64 string in ``ir.config_parameter``.
        """
        res = super().get_values()
        banner = self.env['ir.config_parameter'].sudo().get_param(
            GREETING_BANNER_PARAM,
        )
        res['birthday_greeting_banner'] = banner or False
        return res

    def set_values(self):
        ICP = self.env['ir.config_parameter'].sudo()
        try:
            previous_hour = int(
                ICP.get_param(CRON_HOUR_PARAM, str(DEFAULT_HOUR))
            )
        except (TypeError, ValueError):
            previous_hour = DEFAULT_HOUR
        try:
            previous_greeting_hour = int(
                ICP.get_param(GREETING_HOUR_PARAM, str(DEFAULT_GREETING_HOUR))
            )
        except (TypeError, ValueError):
            previous_greeting_hour = DEFAULT_GREETING_HOUR

        super().set_values()

        new_hour = int(self.birthday_reminder_hour_utc)
        new_active = bool(self.birthday_reminders_enabled)
        new_greeting_hour = int(self.birthday_greeting_hour_utc)

        cron = self.env.ref(CRON_XMLID, raise_if_not_found=False)
        if not cron:
            _logger.warning(
                "Birthday reminders: cron %s missing; cannot sync schedule.",
                CRON_XMLID,
            )
        else:
            cron = cron.sudo()
            desired = {
                'interval_number': 1,
                'interval_type': 'days',
                'active': new_active,
            }
            if new_hour != previous_hour:
                desired['nextcall'] = self._birthday_compute_next_run(new_hour)
            diff = {k: v for k, v in desired.items() if cron[k] != v}
            if diff:
                cron.write(diff)
                _logger.info(
                    "Birthday reminders cron updated %s (hour: %s -> %s).",
                    diff, previous_hour, new_hour,
                )

        # v17.0.2.16.0 — sync the dedicated greeting cron's schedule.
        # Only nextcall is touched on hour change; active stays whatever
        # the admin set on the cron record directly (the greeting
        # feature has its own enable-toggle via the ICP parameter
        # read inside _send_employee_greetings, not mirrored here).
        greeting_cron = self.env.ref(
            GREETING_CRON_XMLID, raise_if_not_found=False,
        )
        if not greeting_cron:
            _logger.warning(
                "Birthday reminders: greeting cron %s missing; "
                "cannot sync schedule.", GREETING_CRON_XMLID,
            )
        else:
            greeting_cron = greeting_cron.sudo()
            gdesired = {
                'interval_number': 1,
                'interval_type': 'days',
            }
            if new_greeting_hour != previous_greeting_hour:
                gdesired['nextcall'] = self._birthday_compute_next_run(
                    new_greeting_hour,
                )
            gdiff = {k: v for k, v in gdesired.items() if greeting_cron[k] != v}
            if gdiff:
                greeting_cron.write(gdiff)
                _logger.info(
                    "Birthday greetings cron updated %s (hour: %s -> %s).",
                    gdiff, previous_greeting_hour, new_greeting_hour,
                )

        # v17.0.2.17.0 — persist the (optional) banner image to ICP.
        # Binary fields in res.config.settings carry the base64 string
        # straight from the upload widget; we store it as-is in the
        # ICP text column so the mail.template QWeb body can render it
        # via ``data:image/*;base64,...``.
        banner = self.birthday_greeting_banner or ''
        if isinstance(banner, bytes):
            banner = banner.decode('ascii')
        ICP.set_param(GREETING_BANNER_PARAM, banner)

    @api.model
    def _birthday_compute_next_run(self, hour_utc):
        """Next UTC datetime at hour:00:00 strictly after now.

        ``ir.cron.nextcall`` is stored as a naive UTC ``Datetime``, so we
        return a naive UTC datetime to match.
        """
        now = fields.Datetime.now()
        candidate = now.replace(
            hour=hour_utc, minute=0, second=0, microsecond=0,
        )
        if candidate <= now:
            candidate = candidate + timedelta(days=1)
        return candidate

    def action_edit_birthday_greeting_template(self):
        """Open the underlying mail.template form for advanced editing.

        The Settings page only exposes a banner upload — for the body
        text, subject, sign-off, and language overlays admins go to
        the standard Email Templates editor (full WYSIWYG, live preview,
        translations). This action is hooked to a button in the
        "Greeting Template" Settings block.
        """
        self.ensure_one()
        template = self.env.ref(
            GREETING_TEMPLATE_XMLID, raise_if_not_found=False,
        )
        if not template:
            raise UserError(_(
                "Greeting template is missing — install or upgrade "
                "the Birthday Reminders module first."
            ))
        return {
            'type': 'ir.actions.act_window',
            'name': _("Edit greeting template"),
            'res_model': 'mail.template',
            'view_mode': 'form',
            'res_id': template.id,
            'target': 'current',
        }

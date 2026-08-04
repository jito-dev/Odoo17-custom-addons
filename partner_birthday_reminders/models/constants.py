"""Shared constants for the contact birthday reminder engine.

Kept in one place so the field/compute layer (``res_partner.py``) and the
cron/dispatch layer (``res_partner_reminder.py``) — two classes on the
same ``res.partner`` model, split for readability — never drift apart.
"""

INTERVAL_7_DAYS = '7_days'
INTERVAL_1_DAY = '1_day'
INTERVAL_ON_DAY = 'on_day'

INTERVAL_OFFSETS = {
    INTERVAL_7_DAYS: 7,
    INTERVAL_1_DAY: 1,
    INTERVAL_ON_DAY: 0,
}

# Per-interval email templates. Each is rendered against a ``res.partner``
# record and sent to the contact's Account Manager (``email_to`` is
# overridden per recipient in ``_send_partner_birthday_email``).
EMAIL_TEMPLATE_XMLIDS = {
    INTERVAL_7_DAYS: 'partner_birthday_reminders.mail_template_partner_birthday_7_days',
    INTERVAL_1_DAY: 'partner_birthday_reminders.mail_template_partner_birthday_1_day',
    INTERVAL_ON_DAY: 'partner_birthday_reminders.mail_template_partner_birthday_today',
}

TODO_ACTIVITY_XMLID = 'mail.mail_activity_data_todo'

# Activity summaries carry this prefix so the daily housekeeping pass can
# recognise (and drop) its own expired To Dos without touching anybody
# else's activities on the same contact.
ACTIVITY_SUMMARY_PREFIX = 'Contact birthday'

GROUP_MANAGER_XMLID = 'partner_birthday_reminders.group_partner_birthday_manager'

# ir.config_parameter keys.
PARAM_CRON_HOUR = 'partner_birthday_reminders.cron_hour_utc'
PARAM_DEFAULT_7_DAYS = 'partner_birthday_reminders.default_notify_7_days'
PARAM_DEFAULT_1_DAY = 'partner_birthday_reminders.default_notify_1_day'
PARAM_DEFAULT_ON_DAY = 'partner_birthday_reminders.default_notify_on_day'

DEFAULT_CRON_HOUR = 6  # 06:00 UTC ≈ 09:00 Kyiv

CRON_XMLID = 'partner_birthday_reminders.ir_cron_partner_birthday_reminders'

# Field-level groups on every birthday field we add to res.partner.
# res.partner is readable by portal and public users in a number of
# flows; birthdays are personal data that must never leak there. Gating
# the fields at declaration time (rather than only in views) also keeps
# them out of the ORM prefetch batch for those users — the same class of
# bug that hr_birthday_reminders had to fix retroactively in v17.0.2.35.0.
BIRTHDAY_FIELD_GROUPS = 'base.group_user'

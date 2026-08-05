"""Shared constants for the contact birthday reminder engine.

Kept in one place so the field/compute layer (``res_partner.py``) and the
cron/dispatch layer (``res_partner_reminder.py``) — two classes on the
same ``res.partner`` model, split for readability — never drift apart.
"""

INTERVAL_7_DAYS = '7_days'
INTERVAL_1_DAY = '1_day'
INTERVAL_ON_DAY = 'on_day'

# The monthly digest is deliberately NOT in INTERVAL_OFFSETS: it is not an
# "N days before the birthday" reminder but a once-a-month planning email,
# driven by its own cron. It shares the log table (and therefore the UNIQUE
# constraint that makes re-runs safe) only as an idempotency device.
INTERVAL_MONTHLY_DIGEST = 'monthly_digest'

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

# The digest renders against a res.users (the manager), not a res.partner —
# it is a list of many contacts, so no single contact can be its record.
EMAIL_TEMPLATE_DIGEST_XMLID = (
    'partner_birthday_reminders.mail_template_partner_birthday_digest'
)

# Hard cap on the rows listed in one monthly digest. A Default Greeter can
# own the entire contact base, which would otherwise produce an email
# thousands of lines long that nobody reads. Over the cap the digest lists
# the first N and says how many more there are.
DIGEST_MAX_ROWS = 100

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
PARAM_DEFAULT_DIGEST = 'partner_birthday_reminders.default_notify_digest'

# Recipient chain (see birthday_manager_ids):
#
#     birthday_greeter_id  ->  user_id  ->  <Default Greeter>  ->  nobody
#
# Inert by default: with no Default Greeter configured,
# birthday_manager_ids resolves to exactly [user_id].
#
# There is deliberately NO "inherit from the parent company" option here.
# Odoo 17 already does that in core: `res.partner.user_id` is a stored,
# precomputed field whose `_compute_user_id` copies the parent company's
# salesperson onto any person contact that has none
# (odoo/addons/base/models/res_partner.py). A setting of our own would
# duplicate core behaviour, and switching it "off" would not stop the
# inheritance — a knob that lies is worse than no knob.
# Comma-separated list of user ids: the Default Greeters, who cover every
# contact the first two steps of the chain do not resolve.
PARAM_FALLBACK_USERS = 'partner_birthday_reminders.fallback_user_ids'

DEFAULT_CRON_HOUR = 6  # 06:00 UTC ≈ 09:00 Kyiv

CRON_XMLID = 'partner_birthday_reminders.ir_cron_partner_birthday_reminders'
CRON_DIGEST_XMLID = 'partner_birthday_reminders.ir_cron_partner_birthday_digest'

# Stored year for contacts whose birth year is unknown.
#
# 1904, not 1900: 1900 is not a leap year, so a Feb-29 birthday could not be
# stored against it at all. 1904 is a leap year and safely pre-dates any
# living contact, so it can never be mistaken for a real date.
BIRTHDAY_UNKNOWN_YEAR = 1904

# Field-level groups on every birthday field we add to res.partner.
# res.partner is readable by portal and public users in a number of
# flows; birthdays are personal data that must never leak there. Gating
# the fields at declaration time (rather than only in views) also keeps
# them out of the ORM prefetch batch for those users — a view-only
# restriction would not.
BIRTHDAY_FIELD_GROUPS = 'base.group_user'

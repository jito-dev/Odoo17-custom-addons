{
    'name': 'Contact Birthday Reminders',
    'version': '17.0.1.0.0',
    'category': 'Sales/CRM',
    'summary': 'Birthday reminders for contacts, delivered privately to '
               'the colleague responsible for greeting them.',
    'description': """
Contact Birthday Reminders
==========================

Adds a **Birthday** field to contacts and reminds the responsible
colleague ahead of it — 7 days before, 1 day before and on the day —
through a To Do activity, a private Odoo notification and an email. Each
recipient chooses which of the three channels they want.

**Nothing is ever sent to the contact themselves.** The reminder is a
private nudge; how, and whether, to greet the client stays a human
decision.

Who receives a reminder
-----------------------

Derived from the contact, so there is no subscription list to maintain:

1. **Birthday Greeter** — an optional field on the contact,
2. otherwise its **Salesperson**,
3. otherwise the **Default Greeters** configured in Settings — a list, so
   several people can cover the whole contact base without any of them
   being assigned contact by contact.

Only real people are tracked: companies, contacts without a birthday,
and contacts linked to an Odoo internal user (current or archived) are
excluded — colleagues' birthdays belong to ``hr_birthday_reminders``.

Also included
-------------

* **Missing Birthdays** — an editable list of contacts that still have no
  date, so the gap is visible and fillable in bulk.
* **Birth year unknown** — record day and month alone. No template ever
  discloses the year, so nobody's age is leaked.
* **Weekend shift** — optionally deliver Saturday and Sunday reminders on
  the preceding Friday.
* **Monthly digest** — opt-in email listing the month's birthdays.
""",
    'author': 'JITO LTD',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'base_setup',  # Settings page (res_config_settings_view_form)
        'mail',
        'contacts',
    ],
    'data': [
        'security/partner_birthday_security.xml',
        'security/ir.model.access.csv',
        'data/mail_template_data.xml',
        'data/mail_template_digest.xml',
        'data/ir_cron_data.xml',
        'views/res_partner_views.xml',
        'views/partner_birthday_pref_views.xml',
        'views/partner_birthday_log_views.xml',
        'views/res_config_settings_views.xml',
        'views/menus.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
    'auto_install': False,
}

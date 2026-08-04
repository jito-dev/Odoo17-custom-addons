{
    'name': 'Contact Birthday Reminders',
    'version': '17.0.1.0.0',
    'category': 'Sales/CRM',
    'summary': 'Birthday reminders for contacts, delivered to the '
               'contact\'s Account Manager (7 days / 1 day / on the day).',
    'description': """
Contact Birthday Reminders
==========================

Adds a Birthday field to contacts and reminds the contact's **Account
Manager** (``res.partner.user_id``) ahead of it — 7 days before, 1 day
before and on the day — through a To Do activity, a private inbox
notification and an email.

Only real people are tracked: company records, contacts without a
birthday, and contacts that are (or ever were) Odoo internal users are
excluded from the Birthdays board and from the reminder engine.

Inspired by ``hr_birthday_reminders`` (employee birthdays), rebuilt for
the customer-facing audience. No automated email is ever sent to the
contact themselves — the Account Manager decides how to greet them.
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

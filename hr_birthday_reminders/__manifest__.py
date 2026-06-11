{
    'name': 'Birthday Reminders',
    'version': '17.0.2.35.0',
    'category': 'Human Resources',
    'summary': 'Per-user birthday reminder subscriptions + personal '
               'greeting email to the employee, with success/failure '
               'chip-marker in the Employees views.',
    'author': 'JITO LTD',
    'license': 'LGPL-3',
    'depends': [
        'hr',
        'mail',
    ],
    'data': [
        'security/birthday_security.xml',
        'security/ir.model.access.csv',
        'data/mail_template_data.xml',
        'data/mail_template_health_alert.xml',
        'data/ir_cron_data.xml',
        'views/birthday_reminder_log_views.xml',
        'views/birthday_reminder_subscription_views.xml',
        'views/birthday_reminder_health_views.xml',
        'views/hr_employee_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}

"""Migration to v17.0.2.0.0.

Convert the legacy global user lists and three boolean toggles (stored in
``ir.config_parameter``) into per-user ``birthday.reminder.subscription``
records. Subscription creation triggers our group-sync hook, which adds
each migrated user to ``group_birthday_responsible``.

After migration the five legacy ``ir.config_parameter`` rows are removed
so they don't linger as dead config.
"""

import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


LEGACY_KEYS = [
    'hr_birthday_reminders.notification_user_ids',
    'hr_birthday_reminders.hr_user_ids',
    'hr_birthday_reminders.notify_7_days_before',
    'hr_birthday_reminders.notify_1_day_before',
    'hr_birthday_reminders.notify_on_day',
]


def _csv_to_ids(value):
    if not value:
        return []
    return [int(p) for p in value.split(',') if p.strip().isdigit()]


def migrate(cr, version):
    if not version:
        # Fresh install — there is no prior config to migrate.
        return

    env = api.Environment(cr, SUPERUSER_ID, {})
    ICP = env['ir.config_parameter']

    notif_csv = ICP.get_param(
        'hr_birthday_reminders.notification_user_ids', default='',
    )
    hr_csv = ICP.get_param(
        'hr_birthday_reminders.hr_user_ids', default='',
    )
    notify_7 = ICP.get_param(
        'hr_birthday_reminders.notify_7_days_before', default='True',
    ) == 'True'
    notify_1 = ICP.get_param(
        'hr_birthday_reminders.notify_1_day_before', default='True',
    ) == 'True'
    notify_on = ICP.get_param(
        'hr_birthday_reminders.notify_on_day', default='True',
    ) == 'True'

    user_ids = sorted(set(_csv_to_ids(notif_csv) + _csv_to_ids(hr_csv)))
    users = env['res.users'].browse(user_ids).exists().filtered('active')

    Sub = env['birthday.reminder.subscription']
    created = 0
    for user in users:
        if Sub.search_count([('user_id', '=', user.id)]):
            continue
        Sub.create({
            'user_id': user.id,
            'notify_7_days_before': notify_7,
            'notify_1_day_before': notify_1,
            'notify_on_day': notify_on,
            'notification_hour': 9,
            'active': True,
        })
        created += 1

    _logger.info(
        "Birthday Reminders v17.0.2.0.0 migration: created %d "
        "subscription(s) from %d legacy user id(s).",
        created, len(user_ids),
    )

    # Clean up legacy config parameters.
    legacy = ICP.search([('key', 'in', LEGACY_KEYS)])
    if legacy:
        legacy.unlink()
        _logger.info(
            "Birthday Reminders v17.0.2.0.0 migration: removed %d legacy "
            "ir.config_parameter row(s).", len(legacy),
        )

    # Convert the cron from daily to hourly. The cron record lives in a
    # noupdate="1" data block, so re-running the XML loader will not flip
    # interval_type. Do it explicitly here.
    cron = env.ref(
        'hr_birthday_reminders.ir_cron_birthday_reminders',
        raise_if_not_found=False,
    )
    if cron:
        update = {}
        if cron.interval_type != 'hours':
            update['interval_type'] = 'hours'
        if cron.interval_number != 1:
            update['interval_number'] = 1
        if cron.name != 'HR: Hourly Birthday Reminders':
            update['name'] = 'HR: Hourly Birthday Reminders'
        if update:
            cron.write(update)
            _logger.info(
                "Birthday Reminders v17.0.2.0.0 migration: updated cron %s",
                update,
            )

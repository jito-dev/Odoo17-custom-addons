"""Migration to v17.0.2.30.0.

Initialise the alert-state ICP keys so the new watchdog cron has a
clean baseline on first run. Without these, the watchdog code paths
that read ``alert_last_status`` would still work (they default to
``'none'``), but explicit initialisation makes the first dashboard
snapshot easier to interpret.

Also re-runs the defensive group resync from v17.0.2.29.0 since the
``group_birthday_manager.implied_ids`` change in this version
implicitly re-syncs membership for managers anyway — but making it
explicit here avoids any edge cases where Odoo's group flush misses
a transitive add.
"""

import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return  # Fresh install — nothing to backfill.
    env = api.Environment(cr, SUPERUSER_ID, {})
    ICP = env['ir.config_parameter'].sudo()

    # 1. Seed alert-state keys so the watchdog never sees missing params.
    # ``get_param`` returns False (Python bool) when key is absent —
    # not None — so use truthiness check.
    if not ICP.get_param('hr_birthday_reminders.alert_last_status'):
        ICP.set_param('hr_birthday_reminders.alert_last_status', 'none')
    if not ICP.get_param('hr_birthday_reminders.alert_last_at'):
        ICP.set_param('hr_birthday_reminders.alert_last_at', '')
    if not ICP.get_param('hr_birthday_reminders.alert_enabled'):
        ICP.set_param('hr_birthday_reminders.alert_enabled', 'True')
    if not ICP.get_param('hr_birthday_reminders.alert_repeat_hours'):
        ICP.set_param('hr_birthday_reminders.alert_repeat_hours', '24')

    # 2. Re-sync group membership (defence-in-depth carried from .29).
    group = env.ref(
        'hr_birthday_reminders.group_birthday_responsible',
        raise_if_not_found=False,
    )
    if not group:
        return
    Sub = env['birthday.reminder.subscription'].sudo()
    target_users = group.users | Sub.search([]).user_id
    if target_users:
        Sub._sync_responsible_group(target_users)
        _logger.info(
            "Birthday Reminders v17.0.2.30.0 migration: re-synced group "
            "membership across %d candidate user(s).", len(target_users),
        )

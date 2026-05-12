"""Migration to v17.0.2.8.0.

Group-membership semantics changed: ``group_birthday_responsible`` now
tracks the EXISTENCE of a subscription (active or paused), not its
active flag. Previously, pausing (active=False) removed the user from
the group, locking them out of their own paused subscription.

Re-run the sync helper for every user that has any subscription so
existing paused-out-of-group users are restored.
"""

import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    Sub = env['birthday.reminder.subscription'].sudo()
    users = Sub.search([]).mapped('user_id')
    if users:
        Sub._sync_responsible_group(users)
        _logger.info(
            "Birthday Reminders v17.0.2.8.0 migration: re-synced group "
            "membership for %d Responsible(s).", len(users),
        )

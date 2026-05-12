"""Migration to v17.0.2.29.0.

Defensive group re-sync. ``-u base`` reloads
``base/data/res_users_data.xml`` which contains
``<field name="groups_id" eval="[Command.set([])]"/>`` for both
``base.user_root`` and ``base.user_admin`` — that temporarily clears
every custom group on these two users, including
``group_birthday_responsible``. The standard base groups are
re-added by the XML, but custom groups are not, so admin silently
falls out of the Responsibles group even though their subscription
still exists.

This is **distinct from** the v17.0.2.8.0 migration, which ran
once when the semantics changed from "active flag in group" to
"existence in group". That migration would have re-added admin
the first time, but only that once — every subsequent ``-u base``
re-strips admin without anyone re-adding them.

The fix here is permanent: this migration runs on every upgrade
to v17.0.2.29.0+, and is also a safety net pattern we can repeat
in any future version that needs it. The body is idempotent — it
walks the union of (current group members) + (every subscription
user) and lets ``_sync_responsible_group`` decide who should be
in or out based on whether they have a subscription. Drift in
either direction is corrected.
"""

import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return  # Fresh install — nothing to reconcile.
    env = api.Environment(cr, SUPERUSER_ID, {})
    group = env.ref(
        'hr_birthday_reminders.group_birthday_responsible',
        raise_if_not_found=False,
    )
    if not group:
        return
    Sub = env['birthday.reminder.subscription'].sudo()
    # Union: anyone currently in the group OR anyone with a subscription.
    # Drift in either direction (member-without-sub, sub-without-member)
    # is corrected by _sync_responsible_group.
    target_users = group.users | Sub.search([]).user_id
    if not target_users:
        return
    before_ids = set(group.users.ids)
    Sub._sync_responsible_group(target_users)
    # Re-read after sync.
    after_ids = set(group.with_user(SUPERUSER_ID).sudo().users.ids)
    added = after_ids - before_ids
    removed = before_ids - after_ids
    if added or removed:
        _logger.info(
            "Birthday Reminders v17.0.2.29.0 migration: re-synced group "
            "membership. Added %d user(s): %s. Removed %d user(s): %s.",
            len(added), sorted(added), len(removed), sorted(removed),
        )
    else:
        _logger.info(
            "Birthday Reminders v17.0.2.29.0 migration: group membership "
            "already consistent (%d members).", len(after_ids),
        )

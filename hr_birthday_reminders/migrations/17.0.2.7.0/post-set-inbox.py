"""Migration to v17.0.2.7.0.

Existing Responsibles likely have ``res.users.notification_type='email'``
(Odoo's default). With that setting, the on-day chatter messages we
post end up only as email — they never appear in the Discuss-Inbox
inside Odoo. From this version on, the subscription ``create()`` hook
auto-flips new Responsibles to ``inbox``; this migration backfills the
flag on every user who is *currently* a Responsible.
"""

import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return  # Fresh install — nothing to backfill.

    # Use ORM (env), not raw SQL, so the registry cache reflects the
    # change. Raw SQL leaves stale 'email' in the in-memory cache; the
    # next ORM write on the same record can flush it back to DB and
    # silently undo the migration.
    env = api.Environment(cr, SUPERUSER_ID, {})
    Sub = env['birthday.reminder.subscription'].sudo()
    users = Sub.search([('active', '=', True)]).mapped('user_id')
    # Skip ``base.user_root`` / ``base.user_admin`` — flipping them to
    # 'inbox' breaks ``-u base`` reload of ``res_users_data.xml`` (those
    # records temporarily clear groups, making share=True, which the
    # mail constraint refuses to combine with 'inbox'). Skip share=True
    # for the same reason.
    system_ids = {
        env.ref(xid).id
        for xid in ('base.user_root', 'base.user_admin')
        if env.ref(xid, raise_if_not_found=False)
    }
    targets = users.filtered(
        lambda u: u.notification_type != 'inbox'
        and u.id not in system_ids
        and not u.share
    )
    if targets:
        targets.write({'notification_type': 'inbox'})
        _logger.info(
            "Birthday Reminders v17.0.2.7.0 migration: switched %d "
            "Responsible(s) to notification_type='inbox': %s",
            len(targets), targets.mapped('login'),
        )

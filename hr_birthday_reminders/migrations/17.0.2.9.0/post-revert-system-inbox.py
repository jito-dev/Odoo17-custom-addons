"""Migration to v17.0.2.9.0.

Older versions of this module unconditionally flipped every Responsible
to ``res.users.notification_type='inbox'`` (the v17.0.2.7.0 migration
and the ``BirthdayReminderSubscription.create()`` hook). When admin
(``base.user_admin``) or ``__system__`` (``base.user_root``) ended up as
a Responsible — even briefly — their notification flag was switched to
'inbox' and stayed that way.

The next ``-u base`` (which the workspace startup script triggers via
``odoo.sh init``) reloads ``base/data/res_users_data.xml``. That XML
contains ``<field name="groups_id" eval="[Command.set([])]"/>`` for
admin, which temporarily turns the user share=True. The ``mail`` SQL
constraint ``CHECK (notification_type='email' OR NOT share)`` then
rejects the row and aborts the registry load — workspace fails to
boot.

This migration sweeps the database and reverts ``notification_type``
back to ``'email'`` on:
- system users (admin / __system__),
- any share user that ended up with 'inbox'.

Regular internal Responsibles are left alone (they are unaffected by
the constraint).
"""

import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return  # Fresh install — nothing to clean up.
    env = api.Environment(cr, SUPERUSER_ID, {})
    sys_ids = [
        env.ref(xid).id
        for xid in ('base.user_root', 'base.user_admin')
        if env.ref(xid, raise_if_not_found=False)
    ]
    Users = env['res.users'].sudo()
    targets = Users.browse([])
    if sys_ids:
        targets |= Users.search([
            ('id', 'in', sys_ids),
            ('notification_type', '=', 'inbox'),
        ])
    targets |= Users.search([
        ('share', '=', True),
        ('notification_type', '=', 'inbox'),
    ])
    if targets:
        targets.write({'notification_type': 'email'})
        _logger.info(
            "Birthday Reminders v17.0.2.9.0 migration: reverted "
            "notification_type='email' on %d system/share user(s): %s",
            len(targets), targets.mapped('login'),
        )

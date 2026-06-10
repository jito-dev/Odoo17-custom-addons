"""Migration to v17.0.2.34.0.

Add ``base.group_system`` to the two Manager-style ir.rule records:

- ``hr_birthday_reminders.rule_subscription_manager_all``
- ``hr_birthday_reminders.rule_log_manager_read_all``

Why a migration and not just the XML edit?

Both rules live inside ``security/birthday_security.xml`` under
``<data noupdate="1">``. The XML was updated in v17.0.2.34.0 to include
``base.group_system`` in the ``groups`` field, but ``noupdate`` tells
Odoo to skip these records on subsequent ``-u`` runs — so the XML edit
alone never reaches existing installs. Without this migration the
fix only applies to **fresh installs**, never to upgrades.

The migration is idempotent: it skips the write if
``base.group_system`` is already present on the rule.

Why ``base.group_system`` at all? See the v17.0.2.34.0 entry in
GUIDANCE.md — system admins were being narrowed by the Responsible
"write own" / "read own + greetings" rules, because they belong to
``group_birthday_responsible`` via their own subscription but not to
``group_birthday_manager``. The Manager rule never matched their
group set, so the per-Responsible restriction was the only write
rule firing.
"""

import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


RULE_XMLIDS = (
    'hr_birthday_reminders.rule_subscription_manager_all',
    'hr_birthday_reminders.rule_log_manager_read_all',
)


def migrate(cr, version):
    if not version:
        return  # Fresh install — XML already loaded the new groups.
    env = api.Environment(cr, SUPERUSER_ID, {})
    sys_grp = env.ref('base.group_system', raise_if_not_found=False)
    if not sys_grp:
        _logger.error(
            "Birthday Reminders v17.0.2.34.0 migration: base.group_system "
            "not found; cannot extend Manager rules."
        )
        return
    for xmlid in RULE_XMLIDS:
        rule = env.ref(xmlid, raise_if_not_found=False)
        if not rule:
            _logger.warning(
                "Birthday Reminders v17.0.2.34.0 migration: %s missing.",
                xmlid,
            )
            continue
        if sys_grp in rule.groups:
            continue  # Idempotent — already extended.
        rule.sudo().write({'groups': [(4, sys_grp.id)]})
        _logger.info(
            "Birthday Reminders v17.0.2.34.0 migration: added "
            "base.group_system to %s.", xmlid,
        )

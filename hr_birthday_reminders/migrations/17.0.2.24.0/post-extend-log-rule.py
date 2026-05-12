"""Migration to v17.0.2.24.0 — extend responsible read rule on log.

The ``rule_log_responsible_read_own`` ir.rule lives inside
``<data noupdate="1">`` in ``security/birthday_security.xml``, so
its ``domain_force`` is NOT auto-updated on ``-u hr_birthday_reminders``.
For existing installs we must rewrite the field explicitly.

Old domain:
    [('user_id', '=', user.id)]

New domain:
    ['|', ('user_id', '=', user.id), ('interval', '=', 'greeting')]

Effect: Responsibles still see only their own per-user reminder
rows; they additionally see all system-emitted greeting rows
(``interval='greeting'``, ``user_id=base.user_root``) so they can
verify automatic greetings went out and avoid duplicating the
gesture.

Idempotent: detects the v24 domain and skips. Detects a
customised domain (one we don't recognise) and preserves it.
"""

import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

RULE_XMLID = 'hr_birthday_reminders.rule_log_responsible_read_own'

OLD_DOMAIN = "[('user_id', '=', user.id)]"
NEW_DOMAIN = "['|', ('user_id', '=', user.id), ('interval', '=', 'greeting')]"


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    rule = env.ref(RULE_XMLID, raise_if_not_found=False)
    if not rule:
        _logger.warning(
            "v17.0.2.24.0: rule %s not found; skipping.", RULE_XMLID,
        )
        return

    current = (rule.domain_force or '').strip()
    if current == NEW_DOMAIN:
        _logger.info(
            "v17.0.2.24.0: log read rule already on v24 domain; skipping."
        )
        return
    if current != OLD_DOMAIN:
        _logger.info(
            "v17.0.2.24.0: log read rule has a customised domain "
            "(%r); preserving as-is.", current,
        )
        return

    rule.sudo().write({
        'name': 'birthday.reminder.log: responsible read own + greetings',
        'domain_force': NEW_DOMAIN,
    })
    _logger.info(
        "v17.0.2.24.0: extended responsible log-read rule to also "
        "include system-emitted greeting rows."
    )

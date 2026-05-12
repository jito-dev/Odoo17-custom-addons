"""Migration to v17.0.2.16.0 — separate greeting-hour knob.

Two idempotent responsibilities:

1. Seed ``ir.config_parameter`` ``hr_birthday_reminders.greeting_hour_utc``
   to ``'6'`` if absent. The Python default callable on
   ``res.config.settings.birthday_greeting_hour_utc`` falls back to
   the same default at read-time, but persisting a value here makes
   the Settings UI render the field as 6 visibly from the first save.

2. Pin the new ``ir_cron_birthday_greetings`` cron's ``nextcall`` to
   the next future occurrence of the configured hour. The XML
   ``<record>`` creates the cron without an explicit ``nextcall``, so
   Odoo defaults it to roughly "now" — which would cause the cron to
   fire immediately on the next scheduler tick. We want the first run
   to land on the chosen UTC hour instead.

The cron's ``active`` flag is intentionally left untouched — admins
who explicitly disabled the cron via Scheduled Actions keep their
state through the upgrade.
"""

import logging
from datetime import timedelta

from odoo import api, fields, SUPERUSER_ID

_logger = logging.getLogger(__name__)

PARAM = 'hr_birthday_reminders.greeting_hour_utc'
CRON_XMLID = 'hr_birthday_reminders.ir_cron_birthday_greetings'
DEFAULT_HOUR = 6


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    ICP = env['ir.config_parameter'].sudo()
    if not ICP.get_param(PARAM):
        ICP.set_param(PARAM, str(DEFAULT_HOUR))
        _logger.info(
            "Birthday Reminders v17.0.2.16.0: seeded %s = %s.",
            PARAM, DEFAULT_HOUR,
        )

    cron = env.ref(CRON_XMLID, raise_if_not_found=False)
    if not cron:
        _logger.warning(
            "Birthday Reminders v17.0.2.16.0: greeting cron %s missing "
            "after install; cannot pin nextcall.", CRON_XMLID,
        )
        return

    try:
        hour = int(ICP.get_param(PARAM, str(DEFAULT_HOUR)))
    except (TypeError, ValueError):
        hour = DEFAULT_HOUR
    now = fields.Datetime.now()
    candidate = now.replace(
        hour=hour, minute=0, second=0, microsecond=0,
    )
    if candidate <= now:
        candidate = candidate + timedelta(days=1)
    cron.sudo().write({
        'interval_number': 1,
        'interval_type': 'days',
        'nextcall': candidate,
    })
    _logger.info(
        "Birthday Reminders v17.0.2.16.0: pinned greeting cron nextcall "
        "to %s UTC.", candidate,
    )

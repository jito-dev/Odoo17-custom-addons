"""Migration to v17.0.2.14.0.

Daily cron + admin-configurable run hour (UTC).

Three responsibilities, each idempotent:

1. Drop the now-removed ``birthday_reminder_subscription.notification_hour``
   column. Odoo 17's auto schema-sync does NOT drop orphan columns by
   default — it logs a warning and leaves the data in place — so we
   issue an explicit ``ALTER TABLE ... DROP COLUMN IF EXISTS``.

2. Seed ``ir.config_parameter`` ``hr_birthday_reminders.cron_hour_utc``
   to the default '6' if no value is present. Admins can override
   afterwards via Settings → Birthday Reminders.

3. Normalise the ``hr_birthday_reminders.ir_cron_birthday_reminders``
   record:
   - ``interval_number=1, interval_type='days'``
   - rename "HR: Hourly Birthday Reminders" → "HR: Daily Birthday
     Reminders"
   - reset ``nextcall`` to the next future occurrence of the configured
     UTC hour.

   The cron's ``active`` flag is intentionally NOT touched — admins who
   disabled the cron (via Scheduled Actions) keep it disabled until they
   re-enable it explicitly through Settings.

Also runs on fresh install (no ``if not version`` gate) so a brand-new
deployment ends up with ``nextcall`` pinned to the configured UTC hour
instead of "whenever the scheduler first ticks".
"""

import logging
from datetime import timedelta

from odoo import api, fields, SUPERUSER_ID

_logger = logging.getLogger(__name__)

CRON_XMLID = 'hr_birthday_reminders.ir_cron_birthday_reminders'
CRON_HOUR_PARAM = 'hr_birthday_reminders.cron_hour_utc'
DEFAULT_HOUR = 6
NEW_CRON_NAME = 'HR: Daily Birthday Reminders'


def _next_run_utc(now_utc, hour):
    candidate = now_utc.replace(hour=hour, minute=0, second=0, microsecond=0)
    if candidate <= now_utc:
        candidate = candidate + timedelta(days=1)
    return candidate


def migrate(cr, version):
    cr.execute(
        "ALTER TABLE birthday_reminder_subscription "
        "DROP COLUMN IF EXISTS notification_hour"
    )
    _logger.info(
        "Birthday Reminders v17.0.2.14.0 migration: ensured "
        "notification_hour column is dropped (no-op if already gone)."
    )

    env = api.Environment(cr, SUPERUSER_ID, {})
    ICP = env['ir.config_parameter'].sudo()
    existing = ICP.search([('key', '=', CRON_HOUR_PARAM)], limit=1)
    if not existing:
        ICP.set_param(CRON_HOUR_PARAM, str(DEFAULT_HOUR))
        _logger.info(
            "Birthday Reminders v17.0.2.14.0 migration: seeded %s = %s.",
            CRON_HOUR_PARAM, DEFAULT_HOUR,
        )
        hour = DEFAULT_HOUR
    else:
        try:
            hour = int(existing.value)
            if not (0 <= hour <= 23):
                raise ValueError(hour)
        except (TypeError, ValueError):
            _logger.warning(
                "Birthday Reminders v17.0.2.14.0 migration: malformed "
                "%s = %r; resetting to %s.",
                CRON_HOUR_PARAM, existing.value, DEFAULT_HOUR,
            )
            ICP.set_param(CRON_HOUR_PARAM, str(DEFAULT_HOUR))
            hour = DEFAULT_HOUR

    cron = env.ref(CRON_XMLID, raise_if_not_found=False)
    if not cron:
        _logger.warning(
            "Birthday Reminders v17.0.2.14.0 migration: cron %s not "
            "found; skipping cron sync.", CRON_XMLID,
        )
        return

    cron_su = cron.sudo()
    desired = {
        'interval_number': 1,
        'interval_type': 'days',
        'name': NEW_CRON_NAME,
        'nextcall': _next_run_utc(fields.Datetime.now(), hour),
    }
    diff = {k: v for k, v in desired.items() if cron_su[k] != v}
    if diff:
        cron_su.write(diff)
        _logger.info(
            "Birthday Reminders v17.0.2.14.0 migration: cron updated %s.",
            diff,
        )
    else:
        _logger.info(
            "Birthday Reminders v17.0.2.14.0 migration: cron already "
            "in target state."
        )

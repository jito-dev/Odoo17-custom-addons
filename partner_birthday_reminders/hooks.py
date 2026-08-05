import logging
from datetime import datetime, timedelta

from odoo import fields

from .models.constants import CRON_XMLID, DEFAULT_CRON_HOUR, PARAM_CRON_HOUR

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    """Pin the cron's first run to the configured UTC hour.

    ``ir.cron.nextcall`` cannot be expressed declaratively as "next
    06:00 UTC", so Odoo seeds it to install time — which would make the
    first batch fire at whatever o'clock the module happened to be
    installed, and then drift a full day away from the hour shown in
    Settings. ``hr_birthday_reminders`` needed a migration script for
    exactly this; doing it in a post-init hook keeps install and
    Settings consistent from the first minute.
    """
    icp = env['ir.config_parameter'].sudo()
    hour = int(icp.get_param(PARAM_CRON_HOUR, DEFAULT_CRON_HOUR))
    icp.set_param(PARAM_CRON_HOUR, hour)

    cron = env.ref(CRON_XMLID, raise_if_not_found=False)
    if not cron:
        _logger.warning("Contact birthday reminders: cron %s not found at "
                        "install; nextcall not pinned.", CRON_XMLID)
        return

    now = fields.Datetime.now()
    nextcall = datetime.combine(now.date(), datetime.min.time()).replace(hour=hour)
    if nextcall <= now:
        nextcall += timedelta(days=1)
    cron.sudo().write({'nextcall': nextcall})
    _logger.info("Contact birthday reminders: first run pinned to %s UTC.",
                 nextcall)

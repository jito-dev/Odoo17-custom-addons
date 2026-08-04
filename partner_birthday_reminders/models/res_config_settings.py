import logging
from datetime import datetime, timedelta

from odoo import api, fields, models

from .constants import (
    CRON_XMLID,
    DEFAULT_CRON_HOUR,
    PARAM_CRON_HOUR,
    PARAM_DEFAULT_1_DAY,
    PARAM_DEFAULT_7_DAYS,
    PARAM_DEFAULT_ON_DAY,
)

_logger = logging.getLogger(__name__)


class ResConfigSettings(models.TransientModel):
    """Settings → Contact Birthday Reminders.

    Two kinds of state are exposed here, both single-source-of-truth:

    * the cron record itself (``active`` and its firing hour, written to
      ``nextcall``) — no shadow copy of the schedule is kept;
    * three ``ir.config_parameter`` defaults used when the cron
      auto-provisions a preference row for a new Account Manager.
      Changing them never rewrites existing rows: people who have tuned
      their own intervals keep them.
    """

    _inherit = 'res.config.settings'

    partner_birthday_cron_active = fields.Boolean(
        string='Enable contact birthday reminders',
        help="Master switch. Mirrors the Scheduled Action; unchecking it "
             "stops all reminders without losing any configuration.",
    )
    partner_birthday_cron_hour = fields.Integer(
        string='Daily run hour (UTC)',
        default=DEFAULT_CRON_HOUR,
        help="UTC hour at which the daily reminder cron fires (0-23). "
             "Each Account Manager is still processed once per *their* "
             "local day, so this only shifts when the batch runs. "
             "Default 6 ≈ 09:00 Kyiv.",
    )
    partner_birthday_default_7_days = fields.Boolean(
        string='New managers get: 7 days before',
        default=True,
    )
    partner_birthday_default_1_day = fields.Boolean(
        string='New managers get: 1 day before',
        default=True,
    )
    partner_birthday_default_on_day = fields.Boolean(
        string='New managers get: on the day',
        default=True,
    )

    # ------------------------------------------------------------------
    @api.model
    def get_values(self):
        res = super().get_values()
        icp = self.env['ir.config_parameter'].sudo()
        cron = self.env.ref(CRON_XMLID, raise_if_not_found=False)
        res.update(
            partner_birthday_cron_active=bool(cron and cron.sudo().active),
            partner_birthday_cron_hour=int(
                icp.get_param(PARAM_CRON_HOUR, DEFAULT_CRON_HOUR)
            ),
            partner_birthday_default_7_days=icp.get_param(
                PARAM_DEFAULT_7_DAYS, 'True') != 'False',
            partner_birthday_default_1_day=icp.get_param(
                PARAM_DEFAULT_1_DAY, 'True') != 'False',
            partner_birthday_default_on_day=icp.get_param(
                PARAM_DEFAULT_ON_DAY, 'True') != 'False',
        )
        return res

    def set_values(self):
        super().set_values()
        icp = self.env['ir.config_parameter'].sudo()
        hour = max(0, min(23, self.partner_birthday_cron_hour or 0))
        previous_hour = int(icp.get_param(PARAM_CRON_HOUR, DEFAULT_CRON_HOUR))

        icp.set_param(PARAM_CRON_HOUR, hour)
        icp.set_param(PARAM_DEFAULT_7_DAYS, self.partner_birthday_default_7_days)
        icp.set_param(PARAM_DEFAULT_1_DAY, self.partner_birthday_default_1_day)
        icp.set_param(PARAM_DEFAULT_ON_DAY, self.partner_birthday_default_on_day)

        cron = self.env.ref(CRON_XMLID, raise_if_not_found=False)
        if not cron:
            _logger.warning(
                "Contact birthday reminders: cron %s not found; schedule "
                "settings not applied.", CRON_XMLID,
            )
            return
        vals = {'active': self.partner_birthday_cron_active}
        # Only move nextcall when the hour actually changed — otherwise
        # every Save on the Settings page would push the next run back by
        # up to a day and quietly skip a batch.
        if hour != previous_hour:
            vals['nextcall'] = self._partner_birthday_next_call(hour)
        cron.sudo().write(vals)

    @api.model
    def _partner_birthday_next_call(self, hour):
        """Next UTC datetime landing on ``hour``:00, strictly in the future."""
        now = fields.Datetime.now()
        candidate = datetime.combine(now.date(), datetime.min.time()).replace(
            hour=hour,
        )
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate

import logging
from datetime import datetime, timedelta

from odoo import _, api, fields, models

from .constants import (
    CRON_DIGEST_XMLID,
    CRON_XMLID,
    DEFAULT_CRON_HOUR,
    PARAM_CRON_HOUR,
    PARAM_DEFAULT_1_DAY,
    PARAM_DEFAULT_7_DAYS,
    PARAM_DEFAULT_DIGEST,
    PARAM_DEFAULT_ON_DAY,
    PARAM_FALLBACK_USERS,
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
    partner_birthday_default_digest = fields.Boolean(
        string='New managers get: monthly digest',
        default=False,
    )
    partner_birthday_digest_active = fields.Boolean(
        string='Enable the monthly digest',
        help="Master switch for the monthly planning email. Individual "
             "managers still choose whether they want it.",
    )
    partner_birthday_fallback_user_ids = fields.Many2many(
        comodel_name='res.users',
        relation='res_config_settings_birthday_greeter_rel',
        column1='config_id',
        column2='user_id',
        string='Default Greeters',
        domain="[('share', '=', False)]",
        help="These people greet every contact that has neither a "
             "Birthday Greeter nor a Salesperson — the whole base at "
             "once, without anyone being written onto individual "
             "contacts. Add several and they all receive. Leave empty to "
             "send nothing for those contacts.",
    )
    # Edge case that would otherwise be invisible: a Default Greeter can
    # pause their own preference row, which silently stops reminders for
    # every contact that resolves to them. One checkbox, thousands of
    # contacts, no error anywhere — so it is surfaced here, on the page
    # where the Default Greeters are chosen.
    partner_birthday_greeter_paused = fields.Char(
        string='Default Greeters who paused their reminders',
        compute='_compute_partner_birthday_coverage',
    )
    # Read-only coverage readout. The whole feature is invisible until
    # birthdays exist, so the number belongs on the page where the
    # feature is switched on — not discovered later via an empty board.
    partner_birthday_coverage = fields.Char(
        string='Data coverage',
        compute='_compute_partner_birthday_coverage',
    )
    partner_birthday_unassigned_count = fields.Integer(
        string='Contacts the Default Greeter would cover',
        compute='_compute_partner_birthday_coverage',
    )

    @api.depends('partner_birthday_fallback_user_ids')
    def _compute_partner_birthday_coverage(self):
        Partner = self.env['res.partner'].sudo()
        Pref = self.env['partner.birthday.pref'].sudo()
        people = [
            ('is_company', '=', False),
            ('active', '=', True),
            ('has_internal_user', '=', False),
        ]
        total = Partner.search_count(people)
        with_birthday = Partner.search_count(people + [('birthday', '!=', False)])
        # Scoped to the chain, not just to Salesperson: a contact that
        # already has a Birthday Greeter will never reach the Default
        # Greeter, so counting it here would overstate the blast radius
        # of switching this setting on.
        unassigned = Partner.search_count(people + [
            ('birthday_greeter_id', '=', False),
            ('user_id', '=', False),
        ])
        for record in self:
            record.partner_birthday_coverage = _(
                "%(filled)s of %(total)s contacts have a birthday",
                filled=with_birthday, total=total,
            )
            record.partner_birthday_unassigned_count = unassigned
            greeters = record.partner_birthday_fallback_user_ids
            # active_test=False: a paused row is archived, so the default
            # search would report "no row" and hide exactly the problem
            # this readout exists to reveal.
            paused = Pref.with_context(active_test=False).search([
                ('user_id', 'in', greeters.ids),
                ('active', '=', False),
            ]) if greeters else Pref.browse()
            record.partner_birthday_greeter_paused = ', '.join(
                paused.mapped('user_id.name')
            )

    # ------------------------------------------------------------------
    @api.model
    def get_values(self):
        res = super().get_values()
        icp = self.env['ir.config_parameter'].sudo()
        cron = self.env.ref(CRON_XMLID, raise_if_not_found=False)
        digest_cron = self.env.ref(CRON_DIGEST_XMLID, raise_if_not_found=False)
        # Resolved through the same validation the engine uses, so a
        # fallback user who has since been archived shows as empty here
        # rather than as a setting that silently does nothing.
        fallback = self.env['res.partner']._birthday_fallback_config()
        res.update(
            partner_birthday_cron_active=bool(cron and cron.sudo().active),
            partner_birthday_digest_active=bool(
                digest_cron and digest_cron.sudo().active
            ),
            partner_birthday_cron_hour=int(
                icp.get_param(PARAM_CRON_HOUR, DEFAULT_CRON_HOUR)
            ),
            partner_birthday_default_7_days=icp.get_param(
                PARAM_DEFAULT_7_DAYS, 'True') != 'False',
            partner_birthday_default_1_day=icp.get_param(
                PARAM_DEFAULT_1_DAY, 'True') != 'False',
            partner_birthday_default_on_day=icp.get_param(
                PARAM_DEFAULT_ON_DAY, 'True') != 'False',
            partner_birthday_default_digest=icp.get_param(
                PARAM_DEFAULT_DIGEST, 'False') == 'True',
            partner_birthday_fallback_user_ids=[(6, 0, fallback.ids)],
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
        icp.set_param(PARAM_DEFAULT_DIGEST, self.partner_birthday_default_digest)

        # Stored sorted so an unchanged selection never looks changed and
        # triggers a needless full recompute.
        previous_fallback = icp.get_param(PARAM_FALLBACK_USERS, '')
        new_fallback = ','.join(
            str(uid) for uid in sorted(self.partner_birthday_fallback_user_ids.ids)
        )
        icp.set_param(PARAM_FALLBACK_USERS, new_fallback)
        # birthday_manager_ids is stored and depends on this value, which
        # the ORM cannot track. Recompute now rather than waiting for the
        # nightly refresh — otherwise the Birthdays board would keep
        # showing the previous recipient and read as a bug.
        if previous_fallback != new_fallback:
            self.env['res.partner']._refresh_partner_birthday_managers()

        digest_cron = self.env.ref(CRON_DIGEST_XMLID, raise_if_not_found=False)
        if digest_cron:
            digest_cron.sudo().write({
                'active': self.partner_birthday_digest_active,
            })

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

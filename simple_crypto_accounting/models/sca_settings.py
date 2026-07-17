import logging
from datetime import datetime, time, timedelta

import pytz

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ScaSettings(models.Model):
    _name = 'sca.settings'
    _description = 'Simple Crypto Accounting Settings'

    lock_field = fields.Char(default='global', copy=False)
    etherscan_api_key = fields.Char(string='Etherscan API Key', copy=False,
        help="Required for ERC-20 watched addresses. Get one free at etherscan.io/apis.")
    trongrid_api_key = fields.Char(string='TronGrid API Key (legacy)',
        copy=False,
        help="Deprecated in 17.0.4.0.0. Retained for migration safety; "
             "not exposed in the UI.")
    cryptoapis_api_key = fields.Char(string='CryptoAPIs API Key (legacy)',
        copy=False,
        help="Deprecated in 17.0.5.0.0 — CryptoAPIs's REST API doesn't "
             "expose TRC-20 transfer listings. Retained for migration "
             "safety; not exposed in the UI.")
    tronscan_api_key = fields.Char(string='Tronscan API Key (optional)',
        copy=False,
        help="Optional for TRC-20 watched addresses (17.0.5.0.0). "
             "Tronscan's public API works without a key for low volume "
             "(rate-limited per IP). For higher throughput, get one at "
             "tronscan.org and we'll send it as the `TRON-PRO-API-KEY` "
             "header to https://apilist.tronscanapi.com/api/.")
    last_sync_date = fields.Datetime(string='Last Sync', readonly=True)

    # ── Periodic (scheduled) Sync ─────────────────────────────────────────────

    periodic_sync_mode = fields.Selection(
        selection=[
            ('off', 'Disabled'),
            ('daily', 'Update daily'),
            ('weekly', 'Update weekly'),
        ],
        string='Periodic Sync',
        default='off',
        copy=False,
        help='When enabled, a scheduled action periodically syncs every watched '
             'address and injects all not-yet-injected transactions into the '
             'Management Ledger.',
    )
    periodic_sync_weekday = fields.Selection(
        selection=[
            ('0', 'Monday'),
            ('1', 'Tuesday'),
            ('2', 'Wednesday'),
            ('3', 'Thursday'),
            ('4', 'Friday'),
            ('5', 'Saturday'),
            ('6', 'Sunday'),
        ],
        string='Day of Week',
        default='0',
        copy=False,
        help='Weekday the weekly sync runs on (used only for "Update weekly").',
    )
    periodic_sync_hour = fields.Integer(
        string='Hour',
        default=23,
        copy=False,
        help='Hour of day (0–23), in the company timezone, the periodic sync runs.',
    )
    periodic_sync_minute = fields.Integer(
        string='Minute',
        default=59,
        copy=False,
        help='Minute of the hour (0–59), in the company timezone.',
    )
    periodic_next_run = fields.Datetime(
        string='Next Scheduled Run',
        compute='_compute_periodic_next_run',
        help='Next run of the periodic-sync scheduled action (UTC).',
    )

    _sql_constraints = [
        ('singleton', 'UNIQUE(lock_field)', 'Only one Crypto Accounting settings record is allowed.'),
    ]

    @api.model
    def _get_singleton(self):
        record = self.sudo().search([], limit=1)
        if not record:
            record = self.sudo().create({'etherscan_api_key': ''})
        return record

    def action_open_settings(self):
        record = self._get_singleton()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Crypto Accounting Settings'),
            'res_model': 'sca.settings',
            'res_id': record.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_open_periodic_sync(self):
        record = self._get_singleton()
        view_id = self.env.ref(
            'simple_crypto_accounting.view_sca_settings_periodic_form').id
        return {
            'type': 'ir.actions.act_window',
            'name': _('Crypto Periodic Sync'),
            'res_model': 'sca.settings',
            'res_id': record.id,
            'view_mode': 'form',
            'view_id': view_id,
            'target': 'current',
        }

    # ── Periodic sync: run pipeline ───────────────────────────────────────────

    def _compute_periodic_next_run(self):
        cron = self.env.ref(
            'simple_crypto_accounting.ir_cron_sca_periodic_sync',
            raise_if_not_found=False)
        next_run = cron.nextcall if (cron and cron.active) else False
        for rec in self:
            rec.periodic_next_run = next_run

    def _run_periodic_sync(self):
        """Shared pipeline for the Sync Now button and the cron: incrementally
        sync every active watched address, then inject all not-yet-injected
        transactions into the Management Ledger. Never raises — per-address sync
        errors are logged and skipped so one bad wallet/API can't abort the run.
        Returns a short human summary string."""
        self.ensure_one()
        Address = self.env['sca.watched_address'].sudo()
        addresses = Address.search([])
        synced_addrs = 0
        total_new = 0
        sync_errors = 0
        for addr in addresses:
            # Mirror action_sync's guard without raising: nothing to pull.
            if not addr.token_ids and not addr.sync_eth_transfers \
                    and not addr.sync_trx_transfers:
                continue
            try:
                total_new += addr._sync_all(full_history=False)
                synced_addrs += 1
            except Exception as exc:
                sync_errors += 1
                _logger.warning(
                    'Crypto periodic sync: address "%s" failed: %s',
                    addr.name, str(exc)[:200])

        Transaction = self.env['sca.transaction'].sudo()
        to_inject = Transaction.search([('is_injected', '=', False)])
        injected_before = len(to_inject)
        if to_inject:
            try:
                # Batch action is idempotent (skips already-injected) and never
                # raises — it collects per-tx errors (e.g. unmapped tokens) itself.
                to_inject.action_inject_to_management_ledger()
            except Exception as exc:
                _logger.exception(
                    'Crypto periodic sync: inject to management ledger failed: %s', exc)
                return _('Synced %d new tx across %d address(es), but injection '
                         'failed: %s') % (total_new, synced_addrs, str(exc)[:200])
        still_uninjected = Transaction.search_count([('is_injected', '=', False)])
        injected_now = injected_before - still_uninjected

        self.sudo().last_sync_date = fields.Datetime.now()
        summary = _(
            'Crypto periodic sync: %(addrs)d address(es) synced (%(errs)d failed), '
            '%(new)d new transaction(s); injected %(inj)d to the Management Ledger '
            '(%(left)d still un-injected — likely awaiting a ledger mapping).'
        ) % {
            'addrs': synced_addrs, 'errs': sync_errors, 'new': total_new,
            'inj': injected_now, 'left': still_uninjected,
        }
        _logger.info(summary)
        return summary

    def action_periodic_sync_now(self):
        """Sync Now button: run the full pipeline immediately (does not touch the
        schedule) and report the result."""
        self.ensure_one()
        summary = self._run_periodic_sync()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Crypto Sync Now'),
                'message': summary,
                'type': 'success',
                'sticky': False,
            },
        }

    @api.model
    def _cron_run_periodic_sync(self):
        """Scheduled-action entry point. Re-checks the mode defensively so a
        disabled schedule is a no-op even if the cron is somehow active."""
        settings = self._get_singleton()
        if settings.periodic_sync_mode == 'off':
            _logger.info('Crypto periodic sync cron fired but mode is Disabled — skipping.')
            return
        settings._run_periodic_sync()

    # ── Periodic sync: scheduling ─────────────────────────────────────────────

    def _periodic_tz(self):
        """Timezone the scheduled time is expressed in: company partner tz, then
        the current user's tz, then UTC."""
        self.ensure_one()
        tz_name = (self.env.company.partner_id.tz
                   or self.env.user.tz or 'UTC')
        try:
            return pytz.timezone(tz_name)
        except Exception:
            return pytz.UTC

    def _compute_periodic_nextcall(self):
        """Next `nextcall` (naive UTC datetime) for the configured local time and,
        for weekly, weekday. Always strictly in the future."""
        self.ensure_one()
        tz = self._periodic_tz()
        now_local = datetime.now(tz)
        hour = min(max(self.periodic_sync_hour or 0, 0), 23)
        minute = min(max(self.periodic_sync_minute or 0, 0), 59)
        candidate = tz.localize(datetime.combine(
            now_local.date(), time(hour=hour, minute=minute)))
        if self.periodic_sync_mode == 'weekly':
            target_wd = int(self.periodic_sync_weekday or '0')
            days_ahead = (target_wd - candidate.weekday()) % 7
            if days_ahead == 0 and candidate <= now_local:
                days_ahead = 7
            candidate = candidate + timedelta(days=days_ahead)
        elif candidate <= now_local:
            candidate = candidate + timedelta(days=1)
        return candidate.astimezone(pytz.UTC).replace(tzinfo=None)

    def _apply_periodic_schedule(self):
        """Reflect the periodic-sync config onto the seeded ir.cron: toggle active,
        set the interval (daily/weekly) and recompute nextcall in UTC."""
        cron = self.env.ref(
            'simple_crypto_accounting.ir_cron_sca_periodic_sync',
            raise_if_not_found=False)
        if not cron:
            return
        for rec in self:
            if rec.periodic_sync_mode == 'off':
                cron.sudo().write({'active': False})
                continue
            interval_type = 'weeks' if rec.periodic_sync_mode == 'weekly' else 'days'
            cron.sudo().write({
                'active': True,
                'interval_number': 1,
                'interval_type': interval_type,
                'nextcall': rec._compute_periodic_nextcall(),
            })

    def action_apply_schedule(self):
        """Save & Apply Schedule button: persist the form then reschedule the cron."""
        self.ensure_one()
        self._apply_periodic_schedule()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Periodic Sync'),
                'message': (_('Schedule disabled.')
                            if self.periodic_sync_mode == 'off'
                            else _('Schedule applied. Next run: %s (UTC).')
                            % (self._compute_periodic_nextcall(),)),
                'type': 'success',
                'sticky': False,
            },
        }

    _PERIODIC_FIELDS = (
        'periodic_sync_mode', 'periodic_sync_weekday',
        'periodic_sync_hour', 'periodic_sync_minute',
    )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if any(f in vals for vals in vals_list for f in self._PERIODIC_FIELDS):
            records._apply_periodic_schedule()
        return records

    def write(self, vals):
        res = super().write(vals)
        if any(f in vals for f in self._PERIODIC_FIELDS):
            self._apply_periodic_schedule()
        return res

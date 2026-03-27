# -*- coding: utf-8 -*-

import logging
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class EcbSyncDashboard(models.Model):
    _name = 'ecb.sync.dashboard'
    _description = 'ECB Sync Dashboard'

    # Singleton enforcement
    lock_field = fields.Char(default='global', copy=False)

    _sql_constraints = [
        ('singleton', 'UNIQUE(lock_field)',
         'Only one ECB Sync Dashboard record is allowed.'),
    ]

    # ── Display fields ───────────────────────────────────────────────

    name = fields.Char(default='ECB Exchange Rate Sync', readonly=True)

    # Sync status (from company)
    sync_status = fields.Selection([
        ('success', 'Success'),
        ('failed', 'Failed'),
        ('never', 'Never Synced'),
    ], string='Sync Status', compute='_compute_dashboard_data')
    last_sync_date = fields.Datetime(
        string='Last Sync',
        compute='_compute_dashboard_data',
    )
    last_sync_error = fields.Char(
        string='Last Error',
        compute='_compute_dashboard_data',
    )
    stale_rate_days = fields.Integer(
        string='Stale Threshold (days)',
        compute='_compute_dashboard_data',
    )

    # Rate statistics
    total_rate_records = fields.Integer(
        string='Total Rate Records',
        compute='_compute_dashboard_data',
    )
    active_currencies = fields.Integer(
        string='Active Currencies',
        compute='_compute_dashboard_data',
    )
    latest_rate_date = fields.Date(
        string='Latest Rate Date',
        compute='_compute_dashboard_data',
    )
    oldest_rate_date = fields.Date(
        string='Oldest Rate Date',
        compute='_compute_dashboard_data',
    )
    rates_today = fields.Integer(
        string='Rates Updated Today',
        compute='_compute_dashboard_data',
    )
    stale_currencies = fields.Integer(
        string='Stale Currencies',
        compute='_compute_dashboard_data',
    )
    stale_currency_names = fields.Char(
        string='Stale Currency Names',
        compute='_compute_dashboard_data',
    )

    # Cron info
    cron_active = fields.Boolean(
        string='Cron Active',
        compute='_compute_cron_data',
    )
    cron_next_call = fields.Datetime(
        string='Next Scheduled Run',
        compute='_compute_cron_data',
    )
    cron_interval = fields.Char(
        string='Cron Interval',
        compute='_compute_cron_data',
    )

    # Company currency
    company_currency = fields.Char(
        string='Base Currency',
        compute='_compute_dashboard_data',
    )

    def _compute_dashboard_data(self):
        company = self.env.company
        CurrencyRate = self.env['res.currency.rate']
        today = fields.Date.context_today(self)

        for rec in self:
            # Sync status from company
            if company.ecb_last_sync_date:
                rec.sync_status = company.ecb_last_sync_status or 'success'
                rec.last_sync_date = company.ecb_last_sync_date
            else:
                rec.sync_status = 'never'
                rec.last_sync_date = False
            rec.last_sync_error = company.ecb_last_sync_error or ''
            rec.stale_rate_days = company.ecb_stale_rate_days or 3
            rec.company_currency = company.currency_id.name

            # Rate statistics
            all_rates = CurrencyRate.search([
                ('company_id', '=', company.id),
            ])
            rec.total_rate_records = len(all_rates)

            if all_rates:
                dates = all_rates.mapped('name')
                rec.latest_rate_date = max(dates)
                rec.oldest_rate_date = min(dates)
            else:
                rec.latest_rate_date = False
                rec.oldest_rate_date = False

            # Rates updated today
            rec.rates_today = CurrencyRate.search_count([
                ('company_id', '=', company.id),
                ('name', '=', today),
            ])

            # Active currencies with rates
            active_curs = self.env['res.currency'].search([
                ('active', '=', True),
            ])
            # Exclude company currency
            foreign_curs = active_curs.filtered(
                lambda c: c.id != company.currency_id.id
            )
            rec.active_currencies = len(foreign_curs)

            # Stale currencies: active foreign currencies with no rate in last N days
            threshold = company.ecb_stale_rate_days or 3
            cutoff_date = today - timedelta(days=threshold)
            stale_names = []
            for cur in foreign_curs:
                recent = CurrencyRate.search([
                    ('currency_id', '=', cur.id),
                    ('company_id', '=', company.id),
                    ('name', '>=', cutoff_date),
                ], limit=1)
                if not recent:
                    stale_names.append(cur.name)

            rec.stale_currencies = len(stale_names)
            rec.stale_currency_names = ', '.join(stale_names[:10]) if stale_names else ''

    def _compute_cron_data(self):
        cron = self.env.ref(
            'jito_ecb_exchange_rate.ir_cron_ecb_rate_download',
            raise_if_not_found=False,
        )
        for rec in self:
            if cron:
                rec.cron_active = cron.active
                rec.cron_next_call = cron.nextcall
                rec.cron_interval = f"{cron.interval_number} {cron.interval_type}"
            else:
                rec.cron_active = False
                rec.cron_next_call = False
                rec.cron_interval = ''

    # ── Singleton access ─────────────────────────────────────────────

    @api.model
    def _get_singleton(self):
        """Get or create the singleton dashboard record."""
        rec = self.search([], limit=1)
        if not rec:
            rec = self.create({'name': 'ECB Exchange Rate Sync'})
        return rec

    # ── Actions ──────────────────────────────────────────────────────

    def action_download_now(self):
        """Trigger immediate ECB rate download."""
        return self.env.company.action_ecb_download_daily()

    def action_open_rates(self):
        """Open the currency rates list view."""
        return {
            'type': 'ir.actions.act_window',
            'name': _('Exchange Rates'),
            'res_model': 'res.currency.rate',
            'view_mode': 'tree,form',
            'domain': [('company_id', '=', self.env.company.id)],
            'context': {'default_company_id': self.env.company.id},
        }

    def action_open_currencies(self):
        """Open the active currencies list."""
        return {
            'type': 'ir.actions.act_window',
            'name': _('Currencies'),
            'res_model': 'res.currency',
            'view_mode': 'tree,form',
            'domain': [('active', '=', True)],
        }

    def action_run_cron(self):
        """Manually trigger the cron job."""
        self.env['res.company']._cron_ecb_download_rates()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('ECB Sync'),
                'message': _('Cron job executed for all companies.'),
                'type': 'success',
                'sticky': False,
            },
        }

    def action_open_settings(self):
        """Open accounting settings (ECB section)."""
        return {
            'type': 'ir.actions.act_window',
            'name': _('Settings'),
            'res_model': 'res.config.settings',
            'view_mode': 'form',
            'target': 'inline',
            'context': {'module': 'account'},
        }

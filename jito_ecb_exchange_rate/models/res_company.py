# -*- coding: utf-8 -*-
import logging
import time
import requests
from datetime import date

from lxml import etree

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

ECB_URL_DAILY = 'https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml'
ECB_URL_HIST_90D = 'https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml'
ECB_URL_HIST_FULL = 'https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.xml'

RETRY_DELAYS = [0, 30, 60]  # seconds between attempts


class ResCompany(models.Model):
    _inherit = 'res.company'

    ecb_last_sync_date = fields.Datetime(
        string='Last ECB Sync',
        readonly=True,
        copy=False,
    )
    ecb_last_sync_status = fields.Selection([
        ('success', 'Success'),
        ('failed', 'Failed'),
    ], string='Last ECB Sync Status', readonly=True, copy=False)
    ecb_last_sync_error = fields.Char(
        string='Last ECB Sync Error',
        readonly=True,
        copy=False,
    )
    ecb_sync_days_ago_text = fields.Char(
        string='Sync Age',
        compute='_compute_ecb_sync_days_ago_text',
    )

    ecb_stale_rate_days = fields.Integer(
        string='Stale Rate Threshold (days)',
        default=3,
        help="Block posting invoices in foreign currencies if exchange rates "
             "are older than this many days. Set to 0 to disable.",
    )

    @api.depends('ecb_last_sync_date')
    def _compute_ecb_sync_days_ago_text(self):
        now = fields.Datetime.now()
        for company in self:
            if company.ecb_last_sync_date:
                days = (now - company.ecb_last_sync_date).days
                if days == 0:
                    company.ecb_sync_days_ago_text = _("today")
                elif days == 1:
                    company.ecb_sync_days_ago_text = _("1 day ago")
                else:
                    company.ecb_sync_days_ago_text = _("%d days ago", days)
            else:
                company.ecb_sync_days_ago_text = _("never")

    # ── Fetching ─────────────────────────────────────────────────────

    def _ecb_fetch_rates_xml(self, url):
        """Fetch and parse ECB XML feed.

        Returns a list of dicts:
            [{'date': date_obj, 'rates': {'USD': 1.089, 'GBP': 0.856, ...}}, ...]
        EUR is always included with rate 1.0.
        """
        response = requests.get(url, timeout=60)
        response.raise_for_status()

        root = etree.fromstring(response.content)
        # ECB XML uses a default namespace
        ns = {'ns': 'http://www.ecb.int/vocabulary/2002-08-01/eurofxref'}

        result = []
        # Each <Cube time="YYYY-MM-DD"> contains child <Cube currency="X" rate="Y"/>
        for time_cube in root.xpath('//ns:Cube[@time]', namespaces=ns):
            rate_date = fields.Date.to_date(time_cube.get('time'))
            rates = {'EUR': 1.0}
            for currency_cube in time_cube.xpath('ns:Cube[@currency]', namespaces=ns):
                currency = currency_cube.get('currency')
                rate = float(currency_cube.get('rate'))
                rates[currency] = rate
            result.append({'date': rate_date, 'rates': rates})

        return result

    def _ecb_fetch_with_retry(self, url, retries=3):
        """Fetch ECB rates with retry and backoff.

        Retries on network/HTTP errors only. Parse errors are not retried.
        Returns parsed data list or raises the last exception.
        """
        last_error = None
        for attempt, delay in enumerate(RETRY_DELAYS[:retries]):
            if delay > 0:
                _logger.info(
                    "ECB retry attempt %d for '%s' after %ds delay",
                    attempt + 1, self.name, delay,
                )
                time.sleep(delay)
            try:
                return self._ecb_fetch_rates_xml(url)
            except requests.exceptions.RequestException as e:
                last_error = e
                _logger.warning(
                    "ECB fetch attempt %d/%d failed for '%s': %s",
                    attempt + 1, retries, self.name, e,
                )
        raise last_error

    def _ecb_fetch_with_fallback(self):
        """Fetch ECB rates with retry on daily URL, then fallback to 90d URL.

        Returns parsed data list or raises on total failure.
        """
        try:
            return self._ecb_fetch_with_retry(ECB_URL_DAILY)
        except requests.exceptions.RequestException:
            _logger.warning(
                "ECB daily feed failed for '%s' after retries, trying 90d fallback",
                self.name,
            )
        # Fallback: 90d history feed (different CDN/URL, same recent data)
        return self._ecb_fetch_with_retry(ECB_URL_HIST_90D)

    # ── Upsert ───────────────────────────────────────────────────────

    def _ecb_upsert_rates(self, parsed_data, date_from=None, date_to=None):
        """Create or update res.currency.rate records from parsed ECB data.

        Args:
            parsed_data: list of {'date': date, 'rates': {currency_code: rate}}
            date_from: optional date filter (inclusive)
            date_to: optional date filter (inclusive)

        Returns:
            tuple (created_count, updated_count)
        """
        Currency = self.env['res.currency']
        CurrencyRate = self.env['res.currency.rate']

        # Get all active currencies indexed by name
        active_currencies = Currency.search([('active', '=', True)])
        currency_by_name = {c.name: c for c in active_currencies}

        company = self
        company_currency_name = company.currency_id.name

        if company_currency_name not in currency_by_name and company_currency_name != 'EUR':
            raise UserError(_(
                "Your company currency (%s) is not found among active currencies. "
                "Please activate it first.",
                company_currency_name,
            ))

        created = 0
        updated = 0
        batch_count = 0

        for entry in parsed_data:
            rate_date = entry['date']

            # Apply date filters if provided
            if date_from and rate_date < date_from:
                continue
            if date_to and rate_date > date_to:
                continue

            ecb_rates = entry['rates']

            # Get the ECB rate for the company's base currency
            # If company currency is EUR, base_rate = 1.0
            base_rate = ecb_rates.get(company_currency_name, None)
            if base_rate is None:
                # Company currency not in ECB data for this date, skip
                _logger.debug(
                    "Skipping date %s: company currency %s not in ECB data",
                    rate_date, company_currency_name,
                )
                continue

            for currency_code, ecb_rate in ecb_rates.items():
                currency = currency_by_name.get(currency_code)
                if not currency:
                    continue

                # Skip the company's own base currency – it is always
                # implicitly 1.0 in Odoo.  Creating explicit rate records
                # for it can interfere with _compute_company_rate.
                if currency.id == company.currency_id.id:
                    continue

                # Normalize: rate relative to company base currency.
                # We write to company_rate (the user-facing field) so that
                # the displayed value matches the ECB rate exactly.  Odoo's
                # _inverse_company_rate then derives the technical `rate`.
                rate_value = ecb_rate / base_rate

                existing = CurrencyRate.search([
                    ('currency_id', '=', currency.id),
                    ('name', '=', rate_date),
                    ('company_id', '=', company.id),
                ], limit=1)

                if existing:
                    if existing.company_rate != rate_value:
                        existing.company_rate = rate_value
                        updated += 1
                else:
                    CurrencyRate.create({
                        'currency_id': currency.id,
                        'company_rate': rate_value,
                        'name': rate_date,
                        'company_id': company.id,
                    })
                    created += 1

                batch_count += 1
                if batch_count % 500 == 0:
                    self.env.cr.commit()  # pylint: disable=invalid-commit

        return created, updated

    # ── Sync status tracking ─────────────────────────────────────────

    def _ecb_mark_success(self):
        """Record a successful ECB sync."""
        self.write({
            'ecb_last_sync_date': fields.Datetime.now(),
            'ecb_last_sync_status': 'success',
            'ecb_last_sync_error': False,
        })

    def _ecb_mark_failure(self, error_message):
        """Record a failed ECB sync and notify admins."""
        self.write({
            'ecb_last_sync_date': fields.Datetime.now(),
            'ecb_last_sync_status': 'failed',
            'ecb_last_sync_error': str(error_message)[:500],
        })
        self._ecb_notify_failure(error_message)

    # ── Admin notification ───────────────────────────────────────────

    def _ecb_notify_failure(self, error_message):
        """Send notification to accounting managers about ECB download failure."""
        self.ensure_one()

        # Find accounting manager users
        group = self.env.ref('account.group_account_manager', raise_if_not_found=False)
        if not group:
            return

        partner_ids = group.users.mapped('partner_id').ids
        if not partner_ids:
            return

        last_success = self.ecb_last_sync_date or _("never")
        body = _(
            "<p><strong>ECB Exchange Rate Download Failed</strong></p>"
            "<p>Company: <strong>%s</strong></p>"
            "<p>Error: %s</p>"
            "<p>Last successful sync: %s</p>"
            "<p>Please check Settings → Accounting → ECB Exchange Rates.</p>",
            self.name,
            str(error_message)[:300],
            last_success,
        )

        self.env['mail.message'].sudo().create({
            'body': body,
            'subject': _("ECB Exchange Rate Download Failed — %s", self.name),
            'message_type': 'notification',
            'model': 'res.company',
            'res_id': self.id,
            'partner_ids': [(6, 0, partner_ids)],
        })

        _logger.error(
            "ECB rate download failed for company '%s': %s",
            self.name, error_message,
        )

    # ── Button actions ───────────────────────────────────────────────

    def action_ecb_download_daily(self):
        """Button action: download latest ECB daily rates for this company."""
        self.ensure_one()
        try:
            parsed_data = self._ecb_fetch_with_fallback()
        except requests.exceptions.RequestException as e:
            self._ecb_mark_failure(e)
            raise UserError(_(
                "Failed to fetch ECB rates after retries: %s", str(e)
            )) from e

        created, updated = self._ecb_upsert_rates(parsed_data)
        self._ecb_mark_success()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("ECB Exchange Rates"),
                'message': _(
                    "Download complete: %d rates created, %d updated.",
                    created, updated,
                ),
                'type': 'success',
                'sticky': False,
            },
        }

    def action_ecb_delete_all_rates(self):
        """Delete all res.currency.rate records for this company."""
        self.ensure_one()
        rates = self.env['res.currency.rate'].search([
            ('company_id', '=', self.id),
        ])
        count = len(rates)
        rates.unlink()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("ECB Exchange Rates"),
                'message': _(
                    "%d exchange rate records deleted.",
                    count,
                ),
                'type': 'warning',
                'sticky': False,
            },
        }

    # ── Cron ─────────────────────────────────────────────────────────

    @api.model
    def _cron_ecb_download_rates(self):
        """Scheduled action: download daily ECB rates for all companies."""
        companies = self.search([])
        for company in companies:
            try:
                parsed_data = company._ecb_fetch_with_fallback()
                created, updated = company._ecb_upsert_rates(parsed_data)
                company._ecb_mark_success()
                _logger.info(
                    "ECB rates for company '%s': %d created, %d updated",
                    company.name, created, updated,
                )
            except Exception as e:
                company._ecb_mark_failure(e)
                _logger.exception(
                    "Failed to download ECB rates for company '%s'",
                    company.name,
                )

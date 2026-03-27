# -*- coding: utf-8 -*-

from odoo import fields, models, _
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _post(self, soft=True):
        self._check_stale_exchange_rates()
        return super()._post(soft=soft)

    def _check_stale_exchange_rates(self):
        """Block posting if exchange rates are stale.

        Checks each move that uses a foreign currency. If the most recent
        exchange rate for that currency is older than the company's threshold,
        raises a UserError to prevent posting with potentially wrong FX.
        """
        CurrencyRate = self.env['res.currency.rate']
        today = fields.Date.context_today(self)

        for move in self:
            # Skip moves in the company's base currency — no FX needed
            if move.currency_id == move.company_currency_id:
                continue

            threshold_days = move.company_id.ecb_stale_rate_days
            if not threshold_days or threshold_days <= 0:
                continue  # check disabled for this company

            latest_rate = CurrencyRate.search([
                ('currency_id', '=', move.currency_id.id),
                ('company_id', '=', move.company_id.id),
            ], order='name desc', limit=1)

            if not latest_rate:
                raise UserError(_(
                    "No exchange rate found for %(currency)s. "
                    "Please download ECB rates before posting.",
                    currency=move.currency_id.name,
                ))

            days_old = (today - latest_rate.name).days
            if days_old > threshold_days:
                raise UserError(_(
                    "Exchange rate for %(currency)s is %(days)d days old "
                    "(last rate: %(date)s). ECB rate download may have failed. "
                    "Please check Settings → Accounting → ECB Exchange Rates.",
                    currency=move.currency_id.name,
                    days=days_old,
                    date=latest_rate.name,
                ))

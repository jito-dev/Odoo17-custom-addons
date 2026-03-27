# -*- coding: utf-8 -*-

from odoo import fields, models, tools


class EcbCurrencyRateStatus(models.Model):
    """SQL view providing per-currency rate status for the dashboard.

    One row per (company, active currency) — excluding the company's own base
    currency — showing the latest rate, date, and freshness.
    """
    _name = 'ecb.currency.rate.status'
    _description = 'ECB Currency Rate Status'
    _auto = False
    _rec_name = 'currency_name'
    _order = 'days_since_update desc, currency_name'

    company_id = fields.Many2one('res.company', string='Company', readonly=True)
    currency_id = fields.Many2one('res.currency', string='Currency', readonly=True)
    currency_name = fields.Char(string='Currency Code', readonly=True)
    latest_rate = fields.Float(string='Rate', readonly=True, digits=(12, 6))
    latest_rate_date = fields.Date(string='Latest Rate Date', readonly=True)
    days_since_update = fields.Integer(string='Days Since Update', readonly=True)

    def _select(self):
        return """
            SELECT
                (comp.id * 100000 + c.id) AS id,
                comp.id AS company_id,
                c.id AS currency_id,
                c.name AS currency_name,
                COALESCE(ROUND((1.0 / NULLIF(lr.rate, 0))::numeric, 6), 0)
                    AS latest_rate,
                lr.rate_date AS latest_rate_date,
                CASE
                    WHEN lr.rate_date IS NULL THEN 9999
                    ELSE (CURRENT_DATE - lr.rate_date)::integer
                END AS days_since_update
        """

    def _from(self):
        return """
            FROM res_currency c
            CROSS JOIN res_company comp
        """

    def _join(self):
        return """
            LEFT JOIN LATERAL (
                SELECT r.rate, r.name AS rate_date
                FROM res_currency_rate r
                WHERE r.currency_id = c.id
                  AND r.company_id = comp.id
                ORDER BY r.name DESC
                LIMIT 1
            ) lr ON true
        """

    def _where(self):
        return """
            WHERE c.active = true
              AND c.id != comp.currency_id
        """

    def init(self):
        tools.drop_view_if_exists(self._cr, self._table)
        self._cr.execute("""
            CREATE OR REPLACE VIEW %s AS (%s %s %s %s)
        """ % (
            self._table,
            self._select(),
            self._from(),
            self._join(),
            self._where(),
        ))

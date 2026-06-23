# -*- coding: utf-8 -*-

"""ML Analytic Distribution Model (17.0.9.0.0).

Parallel to stock ``account.analytic.distribution.model``. Lets the user
predefine an analytic distribution that auto-prefills ML lines based on
partner / partner category / company. Forked from
odoo17_community/addons/analytic/models/analytic_distribution_model.py
with the analytic models retargeted at the ML equivalents.
"""

from odoo import api, fields, models, _
from odoo.tools import SQL
from odoo.exceptions import UserError


class NonMatchingDistribution(Exception):
    pass


class JitoLedgerAnalyticDistributionModel(models.Model):
    _name = 'jito.ledger.analytic.distribution.model'
    _inherit = 'jito.analytic.mixin'
    _description = 'ML Analytic Distribution Model'
    _rec_name = 'create_date'
    _order = 'id desc'

    partner_id = fields.Many2one(
        'res.partner', string='Partner', ondelete='cascade',
        help="Partner for which this analytic distribution will be used "
             "to prefill ML lines.",
    )
    partner_category_id = fields.Many2one(
        'res.partner.category', string='Partner Category', ondelete='cascade',
    )
    company_id = fields.Many2one(
        'res.company', string='Company',
        default=lambda self: self.env.company, ondelete='cascade',
    )

    @api.model
    def _get_distribution(self, vals):
        """Return the distribution JSON of the best-matching model row."""
        domain = []
        for fname, value in vals.items():
            domain += self._create_domain(fname, value) or []
        best_score = 0
        res = {}
        fnames = set(self._get_fields_to_check())
        for rec in self.search(domain):
            try:
                score = sum(rec._check_score(key, vals.get(key)) for key in fnames)
                if score > best_score:
                    res = rec.analytic_distribution
                    best_score = score
            except NonMatchingDistribution:
                continue
        return res

    def _get_fields_to_check(self):
        return (
            {field.name for field in self._fields.values() if not field.manual}
            - set(self.env['jito.analytic.mixin']._fields)
            - set(models.MAGIC_COLUMNS) - {'display_name', '__last_update'}
        )

    def _check_score(self, key, value):
        self.ensure_one()
        if key == 'company_id':
            if not self.company_id or value == self.company_id.id:
                return 1 if self.company_id else 0.5
            raise NonMatchingDistribution
        if not self[key]:
            return 0
        if value and ((self[key].id in value) if isinstance(value, (list, tuple))
                      else (value.startswith(self[key])) if key.endswith('_prefix')
                      else (value == self[key].id)):
            return 1
        raise NonMatchingDistribution

    def _create_domain(self, fname, value):
        if not value:
            return False
        if fname == 'partner_category_id':
            value += [False]
            return [(fname, 'in', value)]
        return [(fname, 'in', [value, False])]

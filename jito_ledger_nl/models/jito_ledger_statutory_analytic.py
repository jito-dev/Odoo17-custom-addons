# -*- coding: utf-8 -*-

"""ML analytic on the FAAP statutory projection (17.0.9.0.0).

The statutory projection (``jito.ledger.statutory.view``) is a read-only
SQL view over real ``account.move.line`` rows. To let users tag analytic
on those projected lines WITHOUT ever writing to stock tables, the
analytic distribution lives here, in a parallel side-table keyed 1:1 by
the stock ``account.move.line`` id.

This model holds no stock data and never writes to ``account.move*``.
"""

from odoo import api, fields, models


class JitoLedgerStatutoryAnalytic(models.Model):
    _name = 'jito.ledger.statutory.analytic'
    _inherit = 'jito.analytic.mixin'
    _description = 'ML Analytic on Statutory Projection'

    move_line_id = fields.Many2one(
        'account.move.line',
        string='Statutory Journal Item',
        required=True, ondelete='cascade', index=True,
        help="The stock journal item this ML analytic distribution "
             "annotates. Read-only reference — never written to.",
    )
    # Related-stored from the stock line so _validate_distribution's
    # with_company() and analytic-account company domains resolve against
    # the statutory line's real company, not env.company.
    company_id = fields.Many2one(
        'res.company',
        related='move_line_id.company_id', store=True, index=True,
    )

    # ---- Read-only projection of the stock line's own analytic (17.0.13.0.0)
    # Translates the stock journal item's native ``analytic_distribution``
    # (keyed by STOCK analytic account ids) into ML *mirror* account ids via
    # the ``statutory_analytic_account_id`` pointer, so FAAP/statutory
    # reporting reflects the real statutory analytic automatically. The manual
    # ``analytic_distribution`` field on this record remains the override.
    projected_distribution = fields.Json(
        string='Projected Distribution (from stock)',
        compute='_compute_projected_distribution', store=False, readonly=True,
        help="Read-only translation of the stock line's own analytic "
             "distribution into ML mirror analytic account ids. The manual "
             "Analytic Distribution overrides this for combined reporting.",
    )

    _sql_constraints = [
        (
            'move_line_uniq',
            'unique(move_line_id)',
            'A statutory journal item can carry only one ML analytic '
            'distribution row.',
        ),
    ]

    @api.depends('move_line_id', 'move_line_id.analytic_distribution',
                 'company_id')
    def _compute_projected_distribution(self):
        """Translate each stock line's own distribution (stock analytic ids)
        into ML mirror ids via the shared helpers on the analytic account."""
        Account = self.env['jito.ledger.analytic.account']
        stock_ids = set()
        for rec in self:
            for key in (rec.move_line_id.analytic_distribution or {}):
                stock_ids.update(int(p) for p in str(key).split(',') if p)
        index = Account._stock_mirror_index(
            stock_ids, self.mapped('company_id').ids)
        for rec in self:
            rec.projected_distribution = Account._project_stock_distribution(
                rec.move_line_id.analytic_distribution or {},
                rec.company_id.id, index,
            )

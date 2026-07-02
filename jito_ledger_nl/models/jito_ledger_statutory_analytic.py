# -*- coding: utf-8 -*-

"""ML analytic on the FAAP statutory projection (17.0.9.0.0).

The statutory projection (``jito.ledger.statutory.view``) is a read-only
SQL view over real ``account.move.line`` rows. To let users tag analytic
on those projected lines WITHOUT ever writing to stock tables, the
analytic distribution lives here, in a parallel side-table keyed 1:1 by
the stock ``account.move.line`` id.

This model holds no stock data and never writes to ``account.move*``.
"""

from odoo import fields, models


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

    _sql_constraints = [
        (
            'move_line_uniq',
            'unique(move_line_id)',
            'A statutory journal item can carry only one ML analytic '
            'distribution row.',
        ),
    ]

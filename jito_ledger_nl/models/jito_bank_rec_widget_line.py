# -*- coding: utf-8 -*-

"""Bank Reconciliation Widget Line — transient (17.0.8.0.0).

Each row represents one candidate counterpart line picked by the user
in the OWL bank-rec widget. ``match_amount`` carries how much of the
counterpart's residual is being matched in this iteration (defaults
to the full residual).
"""

from odoo import api, fields, models


class JitoBankRecWidgetLine(models.TransientModel):
    _name = 'jito.bank.rec.widget.line'
    _description = 'ML Bank Rec Widget Line'

    widget_id = fields.Many2one(
        comodel_name='jito.bank.rec.widget',
        string='Widget',
        required=True,
        ondelete='cascade',
    )
    aml_id = fields.Many2one(
        comodel_name='jito.ledger.move.line',
        string='Counterpart Line',
        ondelete='cascade',
        help='The existing posted line being matched against the '
             'bank-side line. NULL on manual-operation rows (not '
             'shipped in v1; reserved for Phase C).',
    )
    flag = fields.Selection(
        selection=[
            ('aml_match', 'Match Existing'),
            ('manual', 'Manual Operation'),
        ],
        default='aml_match',
        required=True,
    )
    # Display-only related fields for the form table.
    account_id = fields.Many2one(
        related='aml_id.account_id',
        store=False, readonly=True,
    )
    partner_id = fields.Many2one(
        related='aml_id.partner_id',
        store=False, readonly=True,
    )
    date = fields.Date(
        related='aml_id.date',
        store=False, readonly=True,
    )
    label = fields.Char(
        related='aml_id.name',
        store=False, readonly=True,
    )
    move_name = fields.Char(
        related='aml_id.move_name',
        store=False, readonly=True,
    )
    currency_id = fields.Many2one(
        related='aml_id.currency_id',
        store=False, readonly=True,
    )
    aml_amount_currency = fields.Monetary(
        related='aml_id.amount_currency',
        store=False, readonly=True,
        currency_field='currency_id',
    )
    aml_residual = fields.Monetary(
        related='aml_id.amount_residual_currency',
        store=False, readonly=True,
        currency_field='currency_id',
    )
    match_amount = fields.Monetary(
        string='Amount',
        required=True,
        currency_field='currency_id',
        help='How much of the counterpart\'s residual is being '
             'matched in this reconcile. Cannot exceed |residual|.',
    )
    # Signed amount for the widget's balance computation. Equal to
    # `-sign(aml.amount_currency) * match_amount` — i.e. the
    # counterpart's contribution to the bank-line balance.
    signed_match_amount = fields.Monetary(
        compute='_compute_signed_match_amount',
        store=False,
        currency_field='currency_id',
    )

    @api.depends('aml_id.amount_currency', 'match_amount')
    def _compute_signed_match_amount(self):
        for line in self:
            if not line.aml_id:
                line.signed_match_amount = 0.0
                continue
            sign = -1.0 if line.aml_id.amount_currency > 0 else 1.0
            line.signed_match_amount = sign * (line.match_amount or 0.0)

    @api.onchange('aml_id')
    def _onchange_aml_id(self):
        """Auto-fill match_amount with the full residual when an AML
        is picked. User can edit afterwards for partial matches.
        """
        if self.aml_id:
            self.match_amount = abs(self.aml_id.amount_residual_currency)
        else:
            self.match_amount = 0.0

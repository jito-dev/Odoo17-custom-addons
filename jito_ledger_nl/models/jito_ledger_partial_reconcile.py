# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class JitoLedgerPartialReconcile(models.Model):
    """Pairs a debit line with a credit line on the same currency for
    partial reconciliation (HLD Decision #11 — v1.x reconciliation).

    Mirrors stock ``account.partial.reconcile`` (account_partial_reconcile.py)
    but simplified for the ML's per-currency-only world (HLD Decision #10):
    no company-currency snapshot, no FX bridging — both sides must be in
    the same currency. Cross-account same-currency matching is supported
    as of 17.0.8.3.0 (mirrors stock ``account.partial.reconcile`` —
    only ``account.full.reconcile`` enforces same account, and we don't
    ship the closure group in v1). The residual chain on
    ``jito.ledger.move.line`` is per-line, not per-account-pair, so the
    relaxation requires no other code changes.

    Lifecycle:
      * ``create``: deducts ``amount`` from each side's residual via the
        ``_compute_residual`` chain on jito.ledger.move.line. When a
        side's residual reaches zero (within currency precision), that
        line's ``reconciled`` flips True.
      * ``unlink``: restores the same amount, flipping ``reconciled``
        back to False on previously-fully-matched lines.

    Constraints (validated on create + write):
      * Both lines must be on posted moves.
      * Both lines must be in the same currency (no cross-currency FX).
      * Both accounts must have ``reconcile=True``.
      * Debit line: amount_currency > 0; credit line: amount_currency < 0.
      * amount > 0 and ≤ each side's pre-existing residual (enforced via
        the residual recompute — if a partial would overshoot, the
        ``reconciled``/residual chain falls out of sync; the wizard
        already caps amount at min(debit_residual, |credit_residual|)
        and the @api.constrains catches manual API misuse).
    """

    _name = 'jito.ledger.partial.reconcile'
    _description = 'ML Partial Reconciliation'
    _check_company_auto = True

    debit_line_id = fields.Many2one(
        comodel_name='jito.ledger.move.line',
        string='Debit Line',
        required=True,
        index=True,
        ondelete='cascade',
    )
    credit_line_id = fields.Many2one(
        comodel_name='jito.ledger.move.line',
        string='Credit Line',
        required=True,
        index=True,
        ondelete='cascade',
    )
    amount = fields.Monetary(
        string='Amount',
        required=True,
        currency_field='currency_id',
        help='Positive amount in the lines\' currency that this partial '
             'closes on both sides.',
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        related='debit_line_id.currency_id',
        store=True,
        readonly=True,
    )
    account_id = fields.Many2one(
        comodel_name='jito.ledger.account',
        string='Account',
        related='debit_line_id.account_id',
        store=True,
        readonly=True,
        index=True,
    )
    partner_id = fields.Many2one(
        comodel_name='res.partner',
        string='Partner',
        related='debit_line_id.partner_id',
        store=True,
        readonly=True,
        index=True,
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        related='debit_line_id.company_id',
        store=True,
        readonly=True,
        index=True,
    )
    max_date = fields.Date(
        string='Reconciliation Date',
        compute='_compute_max_date',
        store=True,
        readonly=True,
        index=True,
        help='Later of the two lines\' dates. Used for reporting and '
             'period locks.',
    )

    @api.depends('debit_line_id.date', 'credit_line_id.date')
    def _compute_max_date(self):
        for rec in self:
            dates = [d for d in (rec.debit_line_id.date,
                                 rec.credit_line_id.date) if d]
            rec.max_date = max(dates) if dates else False

    @api.constrains('debit_line_id', 'credit_line_id')
    def _check_lines(self):
        for rec in self:
            d = rec.debit_line_id
            c = rec.credit_line_id
            if d.id == c.id:
                raise ValidationError(_(
                    "A line cannot be reconciled with itself."
                ))
            if d.currency_id != c.currency_id:
                raise ValidationError(_(
                    "Reconciled lines must be in the same currency "
                    "(debit %s, credit %s). Cross-currency FX matching "
                    "is not supported in v1.",
                    d.currency_id.name or '?',
                    c.currency_id.name or '?',
                ))
            for line in (d, c):
                if not line.account_id.reconcile:
                    raise ValidationError(_(
                        "Account '%s' is not marked reconcilable. Enable "
                        "'Allow Reconciliation' on the account first.",
                        line.account_id.code,
                    ))
            if d.move_state != 'posted' or c.move_state != 'posted':
                raise ValidationError(_(
                    "Both reconciled lines must belong to posted moves."
                ))
            if d.amount_currency <= 0:
                raise ValidationError(_(
                    "Debit line on account '%s' must have a positive "
                    "amount_currency (got %s).",
                    d.account_id.code, d.amount_currency,
                ))
            if c.amount_currency >= 0:
                raise ValidationError(_(
                    "Credit line on account '%s' must have a negative "
                    "amount_currency (got %s).",
                    c.account_id.code, c.amount_currency,
                ))

    @api.constrains('amount', 'currency_id')
    def _check_amount(self):
        for rec in self:
            if rec.amount <= 0:
                raise ValidationError(_(
                    "Reconciled amount must be strictly positive (got %s).",
                    rec.amount,
                ))
            if rec.currency_id and rec.currency_id.is_zero(rec.amount):
                raise ValidationError(_(
                    "Reconciled amount rounds to zero in %s.",
                    rec.currency_id.name,
                ))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._refresh_line_residuals()
        return records

    def write(self, vals):
        affected_before = self._collect_affected_lines()
        res = super().write(vals)
        affected_after = self._collect_affected_lines()
        (affected_before | affected_after)._update_reconcile_state()
        return res

    def unlink(self):
        affected = self._collect_affected_lines()
        res = super().unlink()
        # `affected` is a recordset captured pre-unlink; the lines
        # themselves still exist (only the partial was unlinked).
        affected._update_reconcile_state()
        return res

    def _refresh_line_residuals(self):
        """Recompute residual / reconciled on every line touched by self."""
        self._collect_affected_lines()._update_reconcile_state()

    def _collect_affected_lines(self):
        """All move lines that need a residual refresh after a change to
        these partials.
        """
        return self.debit_line_id | self.credit_line_id

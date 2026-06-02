# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class JitoLedgerReconcileWizard(models.TransientModel):
    """Manual reconciliation wizard.

    Pre-loaded with a set of jito.ledger.move.line records (via context
    `default_line_ids`) and surfaces a preview of the per-currency
    totals before the user confirms. The actual matching is delegated
    to ``jito.ledger.move.line._reconcile()`` — this wizard is just
    UX + validation.
    """

    _name = 'jito.ledger.reconcile.wizard'
    _description = 'Reconcile ML Lines'

    line_ids = fields.Many2many(
        comodel_name='jito.ledger.move.line',
        string='Lines to Reconcile',
        required=True,
    )
    account_id = fields.Many2one(
        comodel_name='jito.ledger.account',
        string='Account',
        compute='_compute_summary',
        readonly=True,
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        compute='_compute_summary',
        readonly=True,
    )
    total_debit_currency = fields.Monetary(
        string='Open Debit Total',
        currency_field='currency_id',
        compute='_compute_summary',
        readonly=True,
        help='Sum of residual on debit-side lines in the selection.',
    )
    total_credit_currency = fields.Monetary(
        string='Open Credit Total',
        currency_field='currency_id',
        compute='_compute_summary',
        readonly=True,
        help='Sum of |residual| on credit-side lines in the selection.',
    )
    net_currency = fields.Monetary(
        string='Net Open',
        currency_field='currency_id',
        compute='_compute_summary',
        readonly=True,
        help='Open debit minus open credit. Zero = the selection fully '
             'cancels out. Positive = unmatched debit will remain. '
             'Negative = unmatched credit will remain.',
    )
    can_reconcile = fields.Boolean(
        compute='_compute_summary',
        readonly=True,
    )
    blocker_message = fields.Text(
        compute='_compute_summary',
        readonly=True,
        string='Reconcile Blocker',
    )

    @api.depends('line_ids', 'line_ids.amount_residual_currency')
    def _compute_summary(self):
        for wiz in self:
            lines = wiz.line_ids
            unique_accounts = lines.mapped('account_id')
            # Cross-account selections leave account_id blank in the
            # header (17.0.8.3.0). Same-account selections still show the
            # single account.
            wiz.account_id = unique_accounts if len(unique_accounts) == 1 else False
            wiz.currency_id = lines[:1].currency_id
            problems = []
            if len(lines) < 2:
                problems.append(_(
                    "Pick at least two lines (one debit + one credit)."
                ))
            accounts = lines.mapped('account_id')
            # 17.0.8.3.0 — cross-account matching is allowed; stock
            # account.partial.reconcile has the same behavior. We only
            # require every account in the selection to be reconcilable.
            currencies = lines.mapped('currency_id')
            if len(currencies) > 1:
                problems.append(_(
                    "Lines span multiple currencies: %s. Cross-currency "
                    "matching is not supported in v1.",
                    ', '.join(sorted(currencies.mapped('name'))),
                ))
            if accounts and not all(a.reconcile for a in accounts):
                bad = ', '.join(
                    a.code for a in accounts if not a.reconcile
                )
                problems.append(_(
                    "These accounts are not reconcilable: %s. "
                    "Enable 'Allow Reconciliation' on each first.",
                    bad,
                ))
            not_posted = lines.filtered(
                lambda l: l.move_state != 'posted'
            )
            if not_posted:
                problems.append(_(
                    "%d of %d lines belong to non-posted moves.",
                    len(not_posted), len(lines),
                ))
            total_d = sum(
                l.amount_residual_currency for l in lines
                if l.amount_residual_currency > 0
            )
            total_c = sum(
                -l.amount_residual_currency for l in lines
                if l.amount_residual_currency < 0
            )
            wiz.total_debit_currency = total_d
            wiz.total_credit_currency = total_c
            wiz.net_currency = total_d - total_c
            if not problems and (total_d <= 0 or total_c <= 0):
                problems.append(_(
                    "Selection has no debit/credit pair with open "
                    "residual to match."
                ))
            wiz.can_reconcile = not problems
            wiz.blocker_message = '\n'.join(problems) if problems else False

    def action_confirm(self):
        self.ensure_one()
        if not self.can_reconcile:
            raise UserError(
                self.blocker_message
                or _("Selection is not ready to reconcile.")
            )
        created = self.line_ids._reconcile()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Reconciliation'),
                'message': _(
                    "Created %d partial reconcile record(s) totaling %s.",
                    len(created), sum(created.mapped('amount')),
                ),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    @api.model
    def open_for_journal(self, journal):
        """Phase B1 entry point: open the wizard preloaded with all
        unreconciled posted lines on ``journal.bank_account_id``.

        Called by jito.ledger.journal.action_open_reconcile_wizard_for_journal()
        when a bank/cash kanban card's "Reconcile X items" button is
        clicked. Phase B2 will replace this with the OWL bank-rec
        widget (action_open_bank_rec_widget) — the wizard remains
        available for non-bank reconciliation flows.
        """
        if not journal or not journal.bank_account_id:
            raise UserError(_(
                "The journal must have a Bank Account configured to "
                "open the reconcile view."
            ))
        Line = self.env['jito.ledger.move.line'].sudo()
        line_ids = Line.search([
            ('account_id', '=', journal.bank_account_id.id),
            ('move_state', '=', 'posted'),
            ('reconciled', '=', False),
            ('company_id', '=', journal.company_id.id),
        ]).ids
        return {
            'name': _("Reconcile — %s", journal.display_name),
            'type': 'ir.actions.act_window',
            'res_model': 'jito.ledger.reconcile.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_line_ids': [(6, 0, line_ids)],
            },
        }

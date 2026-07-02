# -*- coding: utf-8 -*-

from odoo import api, fields, models, _


class JitoLedgerStatutoryView(models.Model):
    """Read-only FAAP projection of stock account.move.line.

    HLD §4.4 + Decision #13: every stock `account.account` has (or can
    have) a FAAP-mirror in `jito.ledger.account` linked via
    `statutory_account_id`. This SQL-view model surfaces every posted
    stock journal item with its FAAP-mirror account so the Management
    Ledger UI can browse Leading-Ledger entries through the FAAP lens.

    No data duplication — the underlying rows live in `account_move_line`
    and are joined to `jito_ledger_account` at query time.

    Cog actions (Bridge / Restate / Regroup) bind to this model from
    `jito_ledger_adjustments` so the user can dispatch the selected
    line(s) into the appropriate adjustment wizard with a single click.

    Stock pattern reference: `account.invoice.report`
    (odoo17_enterprise/odoo/addons/account/report/account_invoice_report.py).
    """

    _name = 'jito.ledger.statutory.view'
    _description = 'Statutory LL Lines (FAAP Projection)'
    _auto = False
    _order = 'date desc, id desc'
    _rec_name = 'name'

    # The view's primary key matches account_move_line.id 1:1 so cog
    # actions can pass `active_ids` straight into wizards whose
    # source_line_ids field is an M2M to account.move.line.
    move_id = fields.Many2one('account.move', string='Source Move', readonly=True)
    journal_id = fields.Many2one('account.journal', string='Journal', readonly=True)
    date = fields.Date(string='Date', readonly=True)
    name = fields.Char(string='Label', readonly=True)
    partner_id = fields.Many2one('res.partner', string='Partner', readonly=True)

    account_id = fields.Many2one(
        'account.account',
        string='Statutory Account',
        readonly=True,
        help="The original stock account.account this line posts to.",
    )
    faap_account_id = fields.Many2one(
        'jito.ledger.account',
        string='FAAP Account',
        readonly=True,
        help="The FAAP-mirror that projects the statutory account into "
             "the management chart. Empty if no mirror exists yet — run "
             "Configuration → FAAP Mirrors → Sync from Stock CoA.",
    )

    currency_id = fields.Many2one('res.currency', string='Currency', readonly=True)
    amount_currency = fields.Monetary(
        string='Amount',
        currency_field='currency_id',
        readonly=True,
        help="Signed amount in the line's transaction currency. Positive "
             "= debit-side, negative = credit-side.",
    )
    debit = fields.Monetary(
        string='Debit',
        currency_field='company_currency_id',
        readonly=True,
    )
    credit = fields.Monetary(
        string='Credit',
        currency_field='company_currency_id',
        readonly=True,
    )

    company_id = fields.Many2one('res.company', string='Company', readonly=True)
    company_currency_id = fields.Many2one(
        'res.currency', string='Company Currency', readonly=True,
    )

    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('posted', 'Posted'),
            ('cancel', 'Cancelled'),
        ],
        string='Statutory State',
        readonly=True,
    )

    # 17.0.9.0.0 — ML analytic on the statutory projection. The analytic
    # distribution is stored in jito.ledger.statutory.analytic (keyed by
    # the stock line id); surfaced here read-only via the JOIN. Editing
    # goes through action_edit_analytic (a SQL view is not writable).
    analytic_distribution = fields.Json(
        string='Analytic Distribution', readonly=True,
    )

    @property
    def _table_query(self):
        return """
            SELECT
                aml.id              AS id,
                aml.move_id         AS move_id,
                aml.journal_id      AS journal_id,
                aml.date            AS date,
                aml.name            AS name,
                aml.partner_id      AS partner_id,
                aml.account_id      AS account_id,
                fa.id               AS faap_account_id,
                aml.currency_id     AS currency_id,
                aml.amount_currency AS amount_currency,
                aml.debit           AS debit,
                aml.credit          AS credit,
                aml.company_id      AS company_id,
                comp.currency_id    AS company_currency_id,
                aml.parent_state    AS state,
                sa.analytic_distribution AS analytic_distribution
            FROM account_move_line aml
            JOIN res_company comp
              ON comp.id = aml.company_id
            LEFT JOIN jito_ledger_account fa
              ON fa.statutory_account_id = aml.account_id
             AND fa.semantic_family = 'faap'
             AND fa.company_id = aml.company_id
            LEFT JOIN jito_ledger_statutory_analytic sa
              ON sa.move_line_id = aml.id
            WHERE aml.parent_state = 'posted'
        """

    def action_edit_analytic(self):
        """Find-or-create the parallel analytic side-table row for this
        projected stock line, then open the analytic-distribution picker
        on it. Never touches account.move.line.
        """
        self.ensure_one()
        Side = self.env['jito.ledger.statutory.analytic']
        # self.id == account_move_line.id (the SQL view's PK is 1:1).
        side = Side.search([('move_line_id', '=', self.id)], limit=1)
        if not side:
            side = Side.create({'move_line_id': self.id})
        return {
            'type': 'ir.actions.client',
            'tag': 'jito_open_analytic_dialog',
            'params': {
                'res_model': 'jito.ledger.statutory.analytic',
                'res_id': side.id,
                'amount': self.amount_currency,
                'currency_id': self.currency_id.id,
            },
        }

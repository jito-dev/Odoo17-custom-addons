# -*- coding: utf-8 -*-

from odoo import fields, models


class JitoLedgerStatutoryEntryView(models.Model):
    """Read-only FAAP projection of stock account.move (entry-level).

    Companion to ``jito.ledger.statutory.view`` (which is line-level).
    Same idea: surface posted Leading-Ledger entries inside the
    Management Ledger UI without duplicating data, so cog actions can
    dispatch them to the Bridge / Restate / Regroup wizards.

    The cog actions on this model expand each selected move to its lines
    and pop the matching wizard pre-bound.
    """

    _name = 'jito.ledger.statutory.entry.view'
    _description = 'Statutory LL Journal Entries (FAAP Projection)'
    _auto = False
    _order = 'date desc, id desc'
    _rec_name = 'name'

    # Primary key matches account_move.id 1:1 — cog actions expand
    # records.ids → account.move.line.ids via a search by move_id.
    name = fields.Char(string='Number', readonly=True)
    move_id = fields.Many2one(
        'account.move', string='Source Move', readonly=True,
        help="Stock account.move row this projection mirrors.",
    )
    date = fields.Date(string='Date', readonly=True)
    ref = fields.Char(string='Reference', readonly=True)
    journal_id = fields.Many2one('account.journal', string='Journal', readonly=True)
    partner_id = fields.Many2one('res.partner', string='Partner', readonly=True)
    move_type = fields.Selection(
        selection=[
            ('entry',       'Journal Entry'),
            ('out_invoice', 'Customer Invoice'),
            ('out_refund',  'Customer Credit Note'),
            ('in_invoice',  'Vendor Bill'),
            ('in_refund',   'Vendor Refund'),
            ('out_receipt', 'Sales Receipt'),
            ('in_receipt',  'Purchase Receipt'),
        ],
        string='Type',
        readonly=True,
    )
    state = fields.Selection(
        selection=[
            ('draft',  'Draft'),
            ('posted', 'Posted'),
            ('cancel', 'Cancelled'),
        ],
        string='Statutory State',
        readonly=True,
    )

    company_id = fields.Many2one('res.company', string='Company', readonly=True)
    company_currency_id = fields.Many2one('res.currency', readonly=True)
    # 17.0.10.1.1 — original (transaction) currency of the LL move,
    # surfaced so multi-currency invoices/bills don't look like
    # company-currency entries in this projection.
    currency_id = fields.Many2one(
        'res.currency', string='Currency', readonly=True,
        help="Original tx currency of the underlying account.move "
             "(``account_move.currency_id``). Defaults to the company "
             "currency for entries that didn't override it.",
    )
    amount_total = fields.Monetary(
        string='Total (currency)',
        currency_field='currency_id',
        readonly=True,
        help="The LL move's ``amount_total`` in the original "
             "transaction currency. Companion to ``total_debit`` which "
             "is in company currency.",
    )
    total_debit = fields.Monetary(
        string='Total',
        currency_field='company_currency_id',
        readonly=True,
        help="Sum of debit across the move's lines (= sum of credit, "
             "since the move balances). In company currency.",
    )

    line_count = fields.Integer(string='Line Count', readonly=True)

    # 17.0.13.4.0 — entry-level rollup of partial restatement/regrouping
    # consumption, in COMPANY currency (lines may be multi-currency, so the
    # tx-currency figures on the line-level view can't be summed across an
    # entry). Base = ``total_debit`` (the entry's one-sided company-currency
    # total); consumed = Σ|company-currency balance| of the FAAP-reversal
    # postings booked against the entry's source lines; remaining = base −
    # consumed (clamped ≥ 0). Lets users spot & filter partially-consumed
    # entries without drilling into each line.
    consumed_total = fields.Monetary(
        string='Consumed',
        currency_field='company_currency_id',
        readonly=True,
        help="Company-currency total already consumed by restatement / "
             "regrouping across this entry's lines (sum of the FAAP-reversal "
             "postings). See the line-level Statutory Journal Items list for "
             "the per-line, transaction-currency breakdown.",
    )
    remaining_total = fields.Monetary(
        string='Remaining',
        currency_field='company_currency_id',
        readonly=True,
        help="Total (company currency) minus Consumed — the portion of this "
             "entry still re-pickable by a restatement or regrouping.",
    )
    adjustment_status = fields.Selection(
        selection=[
            ('unadjusted', 'Unadjusted'),
            ('partially_adjusted', 'Partially adjusted'),
            ('fully_adjusted', 'Fully adjusted'),
        ],
        string='Adjustment Status',
        readonly=True,
        help="Unadjusted = nothing consumed; Partially = some but not all of "
             "the entry's company-currency total consumed; Fully = consumed "
             "reaches the total.",
    )
    faap_complete = fields.Boolean(
        string='FAAP-Mirrored',
        readonly=True,
        help="True when every line on this move has a FAAP-mirror in the "
             "management chart. False when at least one line's account "
             "has no mirror yet — restatement / regrouping will fail until "
             "you run Configuration → FAAP Mirrors → Sync.",
    )

    @property
    def _table_query(self):
        return """
            SELECT
                am.id                                       AS id,
                am.id                                       AS move_id,
                am.name                                     AS name,
                am.date                                     AS date,
                am.ref                                      AS ref,
                am.journal_id                               AS journal_id,
                am.partner_id                               AS partner_id,
                am.move_type                                AS move_type,
                am.state                                    AS state,
                am.company_id                               AS company_id,
                comp.currency_id                            AS company_currency_id,
                COALESCE(am.currency_id, comp.currency_id)  AS currency_id,
                COALESCE(am.amount_total, 0)                AS amount_total,
                COALESCE(line_summary.total_debit, 0)       AS total_debit,
                COALESCE(line_summary.line_count, 0)        AS line_count,
                COALESCE(line_summary.faap_complete, FALSE) AS faap_complete,
                COALESCE(cons.consumed_cc, 0.0)             AS consumed_total,
                GREATEST(
                    COALESCE(line_summary.total_debit, 0)
                        - COALESCE(cons.consumed_cc, 0.0),
                    0.0
                )                                           AS remaining_total,
                CASE
                    WHEN COALESCE(cons.consumed_cc, 0.0) = 0.0
                        THEN 'unadjusted'
                    WHEN round(
                             (COALESCE(line_summary.total_debit, 0)
                                  - COALESCE(cons.consumed_cc, 0.0))::numeric,
                             COALESCE(ccur.decimal_places, 2)) <= 0.0
                        THEN 'fully_adjusted'
                    ELSE 'partially_adjusted'
                END                                         AS adjustment_status
            FROM account_move am
            JOIN res_company comp ON comp.id = am.company_id
            LEFT JOIN res_currency ccur ON ccur.id = comp.currency_id
            LEFT JOIN (
                SELECT
                    aml.move_id                  AS move_id,
                    COUNT(*)                     AS line_count,
                    SUM(aml.debit)               AS total_debit,
                    BOOL_AND(fa.id IS NOT NULL)  AS faap_complete
                FROM account_move_line aml
                LEFT JOIN jito_ledger_account fa
                  ON fa.statutory_account_id = aml.account_id
                 AND fa.semantic_family       = 'faap'
                 AND fa.company_id            = aml.company_id
                GROUP BY aml.move_id
            ) line_summary ON line_summary.move_id = am.id
            LEFT JOIN (
                -- Company-currency consumed per source ENTRY: sum the
                -- magnitudes of the FAAP-reversal postings (double-count-
                -- safe: only the source line's OWN faap mirror is matched,
                -- so MGT-target / FX-clearing lines are excluded). ABS on
                -- the company-currency ``balance`` so debit- and credit-side
                -- reversals both add to the consumed exposure.
                SELECT src.move_id AS move_id,
                       SUM(ABS(pl.balance)) AS consumed_cc
                  FROM jito_ledger_trace t
                  JOIN jito_ledger_move_line pl ON pl.id = t.parallel_line_id
                  JOIN jito_ledger_account acc  ON acc.id = pl.account_id
                  JOIN account_move_line src    ON src.id = t.source_line_id
                 WHERE t.kind = 'derives_from'
                   AND acc.semantic_family = 'faap'
                   AND acc.statutory_account_id = src.account_id
                   AND pl.move_state = 'posted'
              GROUP BY src.move_id
            ) cons ON cons.move_id = am.id
            WHERE am.state = 'posted'
        """

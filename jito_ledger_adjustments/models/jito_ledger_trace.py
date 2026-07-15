# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class JitoLedgerTrace(models.Model):
    """Provenance join table for FR-10 / FR-11 / FR-22.

    Each row links a `jito.ledger.move.line` (the parallel-ledger line)
    to its provenance — typically a stock `account.move.line` (LL),
    optionally a non-Odoo source via `source_payload_kind` +
    `source_payload`. Carries an immutable `source_snapshot` of the LL
    line's state at trace creation, plus a `weight` for regrouping
    splits.

    Per HLD §8.1 + Decision #4: two B-tree indexes
    (`source_line_id, kind` for reverse lookup; `parallel_line_id, kind`
    for forward lookup). No GIN on source_snapshot in v1.
    """

    _name = 'jito.ledger.trace'
    _description = 'Management-Layer Provenance Trace'
    _order = 'create_date desc, id desc'

    parallel_line_id = fields.Many2one(
        comodel_name='jito.ledger.move.line',
        string='Parallel Line',
        required=True,
        ondelete='cascade',
        index=True,
    )
    parallel_move_id = fields.Many2one(
        comodel_name='jito.ledger.move',
        related='parallel_line_id.move_id',
        store=True,
        readonly=True,
        index=True,
    )

    # Soft FK to the LL source. Nullable: non-Odoo provenance lives in
    # source_payload + source_payload_kind. ondelete='set null' so
    # statutory deletes don't cascade-destroy our trace.
    source_line_id = fields.Many2one(
        comodel_name='account.move.line',
        string='Statutory Source Line',
        ondelete='set null',
        index=True,
    )
    source_move_id = fields.Many2one(
        comodel_name='account.move',
        related='source_line_id.move_id',
        store=True,
        readonly=True,
        index=True,
    )

    source_snapshot = fields.Json(
        string='Source Snapshot',
        readonly=True,
        help="Immutable snapshot of the source line's state at trace "
             "creation. Frozen JSON; even if the LL source line is "
             "later edited or deleted, the snapshot preserves the "
             "exact basis on which this management entry was made.",
    )
    snapshot_version = fields.Char(
        string='Snapshot Version',
        readonly=True,
        default='1',
        help="Schema version of source_snapshot. Bumped on additive "
             "changes; readers tolerate unknown future versions.",
    )

    # Hybrid non-Odoo provenance (Decision #6). When source_line_id is
    # NULL but the parallel line still derives from something (a crypto
    # tx, an external receipt, etc.), source_payload_kind discriminates
    # and source_payload carries the payload.
    source_payload_kind = fields.Selection(
        selection=[
            ('crypto_tx', 'Crypto Transaction'),
            ('external_receipt', 'External Receipt'),
            ('manual_entry', 'Manual Entry'),
        ],
        string='Non-Odoo Source Kind',
        index=True,
    )
    source_payload = fields.Json(
        string='Non-Odoo Source Payload',
        help="Typed JSON payload for non-Odoo provenance. Shape is "
             "documented per kind in jito_ledger_adjustments/"
             "payload_schemas.py. Unknown kinds degrade gracefully — "
             "rendered as raw JSON in reports, no crash.",
    )

    weight = fields.Float(
        string='Weight',
        default=1.0,
        digits=(16, 6),
        help="Fraction of the source contribution carried by this "
             "parallel line (FR-22 regrouping splits). 1.0 means full; "
             "0.4 means 40% of the source's value is reflected here.",
    )

    kind = fields.Selection(
        selection=[
            ('derives_from', 'Derives From'),
            ('clears', 'Clears'),
            ('bridges', 'Bridges'),
            ('reverses', 'Reverses'),
        ],
        string='Provenance Kind',
        required=True,
        default='derives_from',
        index=True,
        help="Discriminator for the semantic relationship: derives_from "
             "(restatement / regrouping output), bridges (mgt_bridge "
             "stage 1), clears (mgt_bridge stage 2 clearance), "
             "reverses (counter-entry of a prior parallel line).",
    )

    company_id = fields.Many2one(
        related='parallel_line_id.company_id',
        store=True,
        readonly=True,
        index=True,
    )

    # ---- constraints -----------------------------------------------------

    @api.constrains('source_line_id', 'source_payload_kind')
    def _check_source_one_of(self):
        """A trace must have at least one source: a statutory line OR a
        typed non-Odoo payload. Never both required, but at least one.
        """
        for trace in self:
            if not trace.source_line_id and not trace.source_payload_kind:
                raise ValidationError(_(
                    "A trace row must have either a statutory source line "
                    "or a non-Odoo source payload (kind + payload). Both "
                    "are missing on a trace for parallel line '%s'.",
                    trace.parallel_line_id.display_name or trace.parallel_line_id.id,
                ))

    @api.constrains('weight')
    def _check_weight_in_range(self):
        for trace in self:
            if trace.weight is None:
                continue
            if trace.weight < 0.0 or trace.weight > 1.0:
                raise ValidationError(_(
                    "Trace weight must be between 0.0 and 1.0; got %s.",
                    trace.weight,
                ))

    # ---- indexes ---------------------------------------------------------

    def init(self):
        """Add the two B-tree composite indexes per HLD Decision #4.

        Indexed columns are already individually `index=True` above
        (parallel_line_id, source_line_id, kind, source_payload_kind).
        These COMPOSITE indexes target the canonical access patterns:
          - reverse: "show all parallel lines that touched LL line X"
          - forward: "show all sources for parallel line Y, by kind"
        """
        cr = self._cr
        cr.execute("""
            CREATE INDEX IF NOT EXISTS jito_ledger_trace_source_kind_idx
            ON jito_ledger_trace (source_line_id, kind)
            WHERE source_line_id IS NOT NULL
        """)
        cr.execute("""
            CREATE INDEX IF NOT EXISTS jito_ledger_trace_parallel_kind_idx
            ON jito_ledger_trace (parallel_line_id, kind)
        """)

    # ---- partial-consumption helpers (17.0.11.0.0) -----------------------
    # How much of a statutory line has already been restated/regrouped is
    # derived DOUBLE-ENTRY, from the actual FAAP-reversal postings — never a
    # stored field. A partial adjustment reverses only the consumed slice of
    # the source's FAAP projection; the reversal line is posted to the
    # source's OWN FAAP mirror (semantic_family='faap' AND
    # statutory_account_id = source.account_id). Summing those reversal
    # amounts gives the consumed amount. (The MGT-target/FX-clearing lines
    # of the same source also carry traces, so we MUST scope to the
    # FAAP-mirror-of-source line to avoid double-counting.)

    @api.model
    def consumed_by_source(self, move_lines):
        """Return ``{account.move.line id: consumed_amount_currency}`` for the
        given source lines, summed from POSTED FAAP-reversal parallel lines
        (kind='derives_from'). Sign matches the source line (a reversal books
        the opposite sign, hence ``-SUM``). Reads live parallel amounts."""
        if not move_lines:
            return {}
        self.env.cr.execute("""
            SELECT t.source_line_id, SUM(-pl.amount_currency)
              FROM jito_ledger_trace t
              JOIN jito_ledger_move_line pl ON pl.id = t.parallel_line_id
              JOIN jito_ledger_account acc  ON acc.id = pl.account_id
              JOIN account_move_line src    ON src.id = t.source_line_id
             WHERE t.kind = 'derives_from'
               AND acc.semantic_family = 'faap'
               AND acc.statutory_account_id = src.account_id
               AND pl.move_state = 'posted'
               AND t.source_line_id IN %s
          GROUP BY t.source_line_id
        """, (tuple(move_lines.ids),))
        return dict(self.env.cr.fetchall())

    @api.model
    def remaining_to_adjust(self, move_lines):
        """Return ``{account.move.line id: remaining_amount_currency}`` =
        source signed amount − consumed, in the source currency (rounded).
        Re-pickable by a later restatement/regrouping."""
        consumed = self.consumed_by_source(move_lines)
        out = {}
        for line in move_lines:
            currency = line.currency_id or line.company_id.currency_id
            src_signed = line.amount_currency or (line.debit - line.credit)
            remaining = src_signed - consumed.get(line.id, 0.0)
            out[line.id] = currency.round(remaining) if currency else remaining
        return out

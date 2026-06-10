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

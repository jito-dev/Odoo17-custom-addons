# -*- coding: utf-8 -*-

import math
from collections import defaultdict

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

from ..snapshot_schemas import snapshot_account_move_line, CURRENT_VERSION
from ..preview import render_preview_table


class JitoMgtRegrouping(models.Model):
    """FR-22 — Management Regrouping.

    M:N split / merge in **amount mode** (17.0.3.0.0). The user picks N
    statutory source lines, defines M target distribution lines (each
    with an account, a partner, a date, and an amount in a currency),
    and the system generates balanced
    ``jito.ledger.move(entry_type='mgt_regroup')`` records:

      * For each (source, target) pair: an MGT line at
        ``source.amount_currency × (target.amount / total_targets_in_currency)``.
      * For each source × date: a FAAP-reversal line on the source's
        FAAP mirror, summing to the proportional share routed to that
        date.

    Strict equality (per HLD §5.5): per currency, sum of target line
    amounts must equal the sum of source line amounts in that currency.
    That guarantees the generated total matches the source total to the
    cent — no rounding drift, no rebalancing line.

    Per-target accounting date support: target lines on different dates
    produce **one move per distinct date**, each move per-currency
    balanced on its own (the FAAP reversal for a given source is split
    across moves proportionally to the share of that source routed to
    each date).
    """

    _name = 'jito.mgt.regrouping'
    _description = 'Management Regrouping (FR-22)'
    _inherit = ['mail.thread']
    _order = 'create_date desc, id desc'
    _check_company_auto = True

    name = fields.Char(
        string='Reference',
        required=True,
        copy=False,
        default=lambda self: _('New'),
        tracking=True,
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('posted', 'Posted'),
        ],
        string='Status',
        default='draft',
        required=True,
        copy=False,
        tracking=True,
    )

    journal_id = fields.Many2one(
        comodel_name='jito.ledger.journal',
        string='Journal',
        required=True,
        tracking=True,
        help="Destination ML journal (17.0.6.0.0 — switched to "
             "jito.ledger.journal).",
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        related='journal_id.company_id',
        store=True,
        readonly=True,
    )

    source_line_ids = fields.Many2many(
        comodel_name='account.move.line',
        relation='jito_mgt_regrouping_source_line_rel',
        column1='regrouping_id',
        column2='line_id',
        string='Statutory Source Lines',
        required=True,
    )
    # 17.0.11.0.0 — per-source consume amounts for PARTIAL regrouping.
    source_consume_ids = fields.One2many(
        'jito.mgt.regrouping.source.line', 'regrouping_id',
        string='Source Consumption', copy=False,
    )
    target_line_ids = fields.One2many(
        comodel_name='jito.mgt.regrouping.target.line',
        inverse_name='regrouping_id',
        string='Target Distributions',
        required=True,
    )

    date = fields.Date(
        string='Default Target Date',
        required=True,
        default=fields.Date.context_today,
        tracking=True,
        help="Used as the default date for new target distribution rows. "
             "Each target row carries its own date — different dates "
             "produce one generated jito.ledger.move per distinct date.",
    )
    reason = fields.Char(
        string='Reason',
        tracking=True,
    )

    generated_move_id = fields.Many2one(
        comodel_name='jito.ledger.move',
        string='Generated Move',
        readonly=True,
        copy=False,
        help="Convenience pointer to the first generated move. When "
             "targets span multiple dates this is the earliest-dated "
             "move; the full set is reachable via `generated_move_ids`.",
    )
    generated_move_ids = fields.Many2many(
        comodel_name='jito.ledger.move',
        relation='jito_mgt_regrouping_generated_move_rel',
        column1='regrouping_id',
        column2='move_id',
        string='Generated Moves',
        readonly=True,
        copy=False,
        help="One row per distinct target date (17.0.3.0.0).",
    )

    # ---- per-currency balance summary (replaces weight totals) ----------

    sources_total_summary = fields.Char(
        string='Sources Total',
        compute='_compute_balance_summary',
        help="Per-currency sum of source line amounts (absolute).",
    )
    targets_total_summary = fields.Char(
        string='Targets Total',
        compute='_compute_balance_summary',
        help="Per-currency sum of target line amounts.",
    )
    is_amounts_balanced = fields.Boolean(
        string='Amounts Balance',
        compute='_compute_balance_summary',
        help="True when per-currency target amounts equal per-currency "
             "source totals exactly. Drives form decoration.",
    )

    @api.depends(
        'source_line_ids',
        'source_consume_ids.consume_amount',
        'target_line_ids.amount',
        'target_line_ids.currency_id',
    )
    def _compute_balance_summary(self):
        for record in self:
            src_per_cur = record._sum_sources_per_currency()
            tgt_per_cur = record._sum_targets_per_currency()
            currencies = set(src_per_cur) | set(tgt_per_cur)
            record.sources_total_summary = ', '.join(
                self._fmt_currency_amount(self.env['res.currency'].browse(cid), abs(amt))
                for cid, amt in sorted(src_per_cur.items())
            ) or '—'
            record.targets_total_summary = ', '.join(
                self._fmt_currency_amount(self.env['res.currency'].browse(cid), amt)
                for cid, amt in sorted(tgt_per_cur.items())
            ) or '—'
            balanced = True
            for cid in currencies:
                currency = self.env['res.currency'].browse(cid)
                if not currency.is_zero(
                    abs(src_per_cur.get(cid, 0.0)) - tgt_per_cur.get(cid, 0.0)
                ):
                    balanced = False
                    break
            record.is_amounts_balanced = bool(currencies) and balanced

    @staticmethod
    def _fmt_currency_amount(currency, amount):
        return '%s %s' % (currency.symbol or currency.name, amount)

    def _sum_sources_per_currency(self):
        """Sum the CONSUMED slice of each source per currency (partial
        regrouping). Targets must balance the consumed portion, not the full
        source amount.
        """
        self.ensure_one()
        cm = self._consume_map()
        totals = defaultdict(float)
        for src in self.source_line_ids:
            currency = src.currency_id or src.company_id.currency_id
            totals[currency.id] += self._consume_signed(src, cm)
        return dict(totals)

    # ---- partial-consumption helpers (17.0.11.0.0) ----------------------
    def _consume_map(self):
        """{move_line_id: consume_amount magnitude}; falls back to each line's
        REMAINING (not the full amount) for any source lacking a consume row,
        so an unsynced row still previews the consumable slice."""
        self.ensure_one()
        m = {r.move_line_id.id: r.consume_amount for r in self.source_consume_ids}
        missing = self.source_line_ids.filtered(lambda l: l.id not in m)
        if missing:
            rem = self.env['jito.ledger.trace'].remaining_to_adjust(missing)
            for line in missing:
                m[line.id] = abs(rem.get(
                    line.id, line.amount_currency or (line.debit - line.credit)))
        return m

    def _consume_signed(self, src, consume_map=None):
        cm = consume_map if consume_map is not None else self._consume_map()
        src_signed = src.amount_currency or (src.debit - src.credit)
        currency = src.currency_id or src.company_id.currency_id
        mag = cm.get(src.id, abs(src_signed))
        mag = currency.round(mag) if currency else mag
        return math.copysign(mag, src_signed or 1.0)

    def _consume_fraction(self, src, consume_map=None):
        src_signed = src.amount_currency or (src.debit - src.credit)
        if not src_signed:
            return 1.0
        return min(1.0, abs(self._consume_signed(src, consume_map)) / abs(src_signed))

    @api.onchange('source_line_ids')
    def _onchange_sync_consume_rows(self):
        Trace = self.env['jito.ledger.trace']
        existing = {r.move_line_id.id: r for r in self.source_consume_ids}
        rem = Trace.remaining_to_adjust(self.source_line_ids)
        cmds = []
        for aml in self.source_line_ids:
            if aml.id not in existing:
                default = abs(rem.get(aml.id, aml.amount_currency or 0.0))
                cmds.append((0, 0, {'move_line_id': aml.id, 'consume_amount': default}))
        for mlid, row in existing.items():
            if mlid not in self.source_line_ids.ids:
                cmds.append((2, row.id))
        if cmds:
            self.source_consume_ids = cmds

    @api.onchange('source_consume_ids')
    def _onchange_sync_source_lines(self):
        lines = self.source_consume_ids.mapped('move_line_id')
        if set(lines.ids) != set(self.source_line_ids.ids):
            self.source_line_ids = [(6, 0, lines.ids)]

    def _ensure_consume_rows(self):
        """Reconcile consume rows ↔ M2M so both agree before generate
        (consume rows are authoritative)."""
        self.ensure_one()
        Trace = self.env['jito.ledger.trace']
        have = self.source_consume_ids.mapped('move_line_id').ids
        missing = self.source_line_ids.filtered(lambda l: l.id not in have)
        if missing:
            rem = Trace.remaining_to_adjust(missing)
            self.source_consume_ids = [
                (0, 0, {'move_line_id': l.id,
                        'consume_amount': abs(rem.get(l.id, l.amount_currency or 0.0))})
                for l in missing
            ]
        lines = self.source_consume_ids.mapped('move_line_id')
        if set(lines.ids) != set(self.source_line_ids.ids):
            self.source_line_ids = [(6, 0, lines.ids)]

    def _check_consume_within_remaining(self):
        self.ensure_one()
        Trace = self.env['jito.ledger.trace']
        rem = Trace.remaining_to_adjust(self.source_consume_ids.mapped('move_line_id'))
        for row in self.source_consume_ids:
            currency = row.currency_id or self.company_id.currency_id
            remaining = abs(rem.get(row.move_line_id.id, 0.0))
            amt = row.consume_amount
            if not currency or currency.is_zero(amt) or amt < 0:
                raise UserError(_(
                    "Consume amount must be greater than zero (source line %s).",
                    row.move_line_id.display_name,
                ))
            if currency.compare_amounts(amt, remaining) > 0:
                raise UserError(_(
                    "Cannot consume %(amt)s of source line %(line)s — only "
                    "%(rem)s remaining.",
                    amt=amt, line=row.move_line_id.display_name, rem=remaining,
                ))

    def _sum_targets_per_currency(self):
        self.ensure_one()
        totals = defaultdict(float)
        for tgt in self.target_line_ids:
            if not tgt.currency_id or not tgt.amount:
                continue
            totals[tgt.currency_id.id] += tgt.amount
        return dict(totals)

    # ---- preview (17.0.2.2.0 / 17.0.3.0.0) ------------------------------

    preview_html = fields.Html(
        string='Preview',
        compute='_compute_preview_html',
        sanitize=False,
        readonly=True,
    )

    @api.depends(
        'source_line_ids',
        'source_consume_ids.consume_amount',
        'target_line_ids',
        'target_line_ids.target_account_id',
        'target_line_ids.amount',
        'target_line_ids.currency_id',
        'target_line_ids.date',
        'target_line_ids.partner_id',
    )
    def _compute_preview_html(self):
        for record in self:
            record.preview_html = render_preview_table(
                record._build_preview_lines()
            )

    def _build_preview_lines(self):
        """For each (source, target) pair: FAAP reversal + MGT target line.

        Allocation uses amount mode: each source's amount is split across
        targets in the **same currency** proportionally to
        ``target.amount / sum_targets_in_currency``. Lines from different
        target dates are flagged in the label so the preview reflects the
        per-date split.
        """
        self.ensure_one()
        lines = []
        if not self.source_line_ids or not self.target_line_ids:
            return lines
        tgt_totals = self._sum_targets_per_currency()
        cm = self._consume_map()
        for src in self.source_line_ids:
            src_signed = self._consume_signed(src, cm)
            currency = src.currency_id or src.company_id.currency_id
            faap_account = self._faap_mirror_for(src.account_id)
            currency_total = tgt_totals.get(currency.id) or 0.0
            if not currency_total:
                continue
            lines.append({
                'account_code': (faap_account and faap_account.code)
                                or ('FAAP-mirror-of-' + src.account_id.code),
                'name': _("Regroup from %s") % src.account_id.code,
                'currency_symbol': currency.symbol,
                'debit':  -src_signed if src_signed < 0 else 0.0,
                'credit':  src_signed if src_signed > 0 else 0.0,
            })
            for target in self.target_line_ids:
                if (target.currency_id.id != currency.id
                        or not target.target_account_id
                        or not target.amount):
                    continue
                ratio = target.amount / currency_total
                portion = currency.round(src_signed * ratio)
                if currency.is_zero(portion):
                    continue
                date_tag = (
                    ' @ %s' % fields.Date.to_string(target.date)
                    if target.date else ''
                )
                lines.append({
                    'account_code': target.target_account_id.code,
                    'name': target.name or _(
                        "→ %s (%s %s)%s",
                        target.target_account_id.code,
                        target.amount,
                        currency.symbol or currency.name,
                        date_tag,
                    ),
                    'currency_symbol': currency.symbol,
                    'debit':  portion if portion > 0 else 0.0,
                    'credit': -portion if portion < 0 else 0.0,
                })
        return lines

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if 'journal_id' in fields_list and not res.get('journal_id'):
            jid = self.env['jito.ledger.move']._resolve_default_adjustments_journal()
            if jid:
                res['journal_id'] = jid
        return res

    # ---- constraints -----------------------------------------------------

    @api.constrains('target_line_ids', 'source_line_ids',
                    'source_consume_ids', 'state')
    def _check_amount_strict_equality(self):
        """Strict equality per HLD §5.5 in amount mode: per currency, target
        amounts must equal the absolute sum of the CONSUMED source amounts
        (17.0.11.0.0 — targets balance the consumed slice, not the full
        source; the un-consumed remainder stays re-pickable).
        """
        for record in self:
            if record.state == 'draft':
                continue
            if not record.target_line_ids:
                raise ValidationError(_(
                    "Regrouping '%s' has no target distribution lines.",
                    record.name,
                ))
            src_per_cur = record._sum_sources_per_currency()
            tgt_per_cur = record._sum_targets_per_currency()
            currencies = set(src_per_cur) | set(tgt_per_cur)
            for cid in currencies:
                currency = self.env['res.currency'].browse(cid)
                src_abs = abs(src_per_cur.get(cid, 0.0))
                tgt_total = tgt_per_cur.get(cid, 0.0)
                if not currency.is_zero(src_abs - tgt_total):
                    raise ValidationError(_(
                        "Regrouping '%s' is unbalanced in %s: consumed "
                        "sources %s vs. targets %s. Per-currency target total "
                        "must equal the consumed source total (FR-22).",
                        record.name, currency.name, src_abs, tgt_total,
                    ))

    # ---- workflow --------------------------------------------------------

    def action_post(self):
        for record in self:
            if record.state != 'draft':
                raise UserError(_(
                    "Only draft regroupings can be posted (record '%s' "
                    "is %s).", record.name, record.state,
                ))
            if not record.source_line_ids:
                raise UserError(_("Pick at least one statutory source line."))
            if not record.target_line_ids:
                raise UserError(_("Define at least one target distribution line."))
            record._ensure_consume_rows()
            record._check_consume_within_remaining()
            if record.name == _('New'):
                seq = self.env['ir.sequence'].with_company(
                    record.company_id
                ).next_by_code('jito.mgt.regrouping') or _('New')
                record.name = seq
            moves = record._generate_moves()
            record.write({
                'state': 'posted',
                'generated_move_id': moves[0].id if moves else False,
                'generated_move_ids': [(6, 0, moves.ids)],
            })
            record.message_post(body=_(
                "Regrouping posted: %s.",
                ', '.join(m.display_name for m in moves),
            ))
        return True

    def action_draft(self):
        """Reset a posted regrouping back to draft and delete the
        generated jito.ledger.move records (and their lines + trace
        rows, both of which cascade).

        Refuses if any generated move was further manipulated (reversed
        or destructively voided) — the safe path then is to manually
        reverse the regrouping's outputs rather than wipe them.
        """
        for record in self:
            if record.state != 'posted':
                raise UserError(_(
                    "Only posted regroupings can be reset to draft "
                    "(record '%s' is %s).",
                    record.name, record.state,
                ))
            moves = record.generated_move_ids
            for move in moves:
                if move.state == 'reversed' or move.reversal_move_ids:
                    raise UserError(_(
                        "Generated move '%s' has been reversed; reset "
                        "to draft would orphan the reversal. Reverse "
                        "the counter-entries first.",
                        move.display_name,
                    ))
                if move.is_voided:
                    raise UserError(_(
                        "Generated move '%s' is voided. Restore it "
                        "first or contact an administrator.",
                        move.display_name,
                    ))
            # Two-phase: bring posted moves to draft, then unlink.
            posted = moves.filtered(lambda m: m.state == 'posted')
            if posted:
                posted.action_draft()
            moves.unlink()
            record.write({
                'state': 'draft',
                'generated_move_id': False,
                'generated_move_ids': [(5, 0, 0)],
            })
            record.message_post(body=_(
                "Regrouping reset to draft; %s generated move(s) deleted.",
                len(moves),
            ))
        return True

    def _generate_moves(self):
        """Create one balanced jito.ledger.move per distinct target date.

        Each move contains, for the targets dated on that day:
          * For each (source, target_on_this_date) pair:
              - one FAAP-reversal line at -portion (slice of source)
              - one MGT line at +portion (on target.target_account_id,
                partner=target.partner_id)
        where ``portion = source.amount × (target.amount / total_in_currency)``.

        Per-currency balance holds within each move because every MGT
        line is paired with its own FAAP reversal slice of the same
        magnitude.
        """
        self.ensure_one()
        Move = self.env['jito.ledger.move']
        Line = self.env['jito.ledger.move.line']
        Trace = self.env['jito.ledger.trace']

        tgt_per_cur = self._sum_targets_per_currency()
        cm = self._consume_map()
        # Group targets by date so we generate one move per date.
        targets_by_date = defaultdict(list)
        for target in self.target_line_ids:
            targets_by_date[target.date or self.date].append(target)

        moves = self.env['jito.ledger.move']
        for date, targets in sorted(targets_by_date.items()):
            move = Move.create({
                'journal_id': self.journal_id.id,
                'date': date,
                'entry_type': 'mgt_regroup',
                'ref': _("Regroup %s @ %s") % (self.name, date),
                'state': 'draft',
                'name': _('New'),
                'reason': self.reason,
                'adjustment_origin': '%s,%s' % (self._name, self.id),
            })
            for src in self.source_line_ids:
                # 17.0.11.0.0 — prorate over the CONSUMED slice, not the full
                # source. orig_src is kept for the trace weight (fraction of
                # the original source this slice represents).
                orig_src = src.amount_currency or (src.debit - src.credit)
                src_signed = self._consume_signed(src, cm)
                currency = src.currency_id or src.company_id.currency_id
                currency_total = tgt_per_cur.get(currency.id) or 0.0
                if not currency_total:
                    continue
                faap_account = self._faap_mirror_for(src.account_id)
                if not faap_account:
                    raise UserError(_(
                        "No FAAP mirror for stock account '%s'. Run "
                        "Configuration → FAAP Mirrors → Sync from Stock CoA.",
                        src.account_id.code,
                    ))
                for target in targets:
                    if (target.currency_id.id != currency.id
                            or not target.amount):
                        continue
                    ratio = target.amount / currency_total
                    portion = currency.round(src_signed * ratio)
                    if currency.is_zero(portion):
                        continue
                    # weight = fraction of the ORIGINAL source this slice is.
                    weight = (min(1.0, abs(portion) / abs(orig_src))
                              if orig_src else 1.0)
                    faap_line = Line.create({
                        'move_id': move.id,
                        'account_id': faap_account.id,
                        'name': _("Regroup from %s → %s") % (
                            src.account_id.code, target.target_account_id.code,
                        ),
                        'currency_id': currency.id,
                        'amount_currency': -portion,
                    })
                    Trace.create({
                        'parallel_line_id': faap_line.id,
                        'source_line_id': src.id,
                        'source_snapshot': snapshot_account_move_line(src),
                        'snapshot_version': CURRENT_VERSION,
                        'kind': 'derives_from',
                        'weight': weight,
                    })
                    mgt_line = Line.create({
                        'move_id': move.id,
                        'account_id': target.target_account_id.id,
                        'partner_id': target.partner_id.id or False,
                        'name': target.name or _(
                            "Regroup to %s",
                            target.target_account_id.code,
                        ),
                        'currency_id': currency.id,
                        'amount_currency': portion,
                    })
                    Trace.create({
                        'parallel_line_id': mgt_line.id,
                        'source_line_id': src.id,
                        'source_snapshot': snapshot_account_move_line(src),
                        'snapshot_version': CURRENT_VERSION,
                        'kind': 'derives_from',
                        'weight': weight,
                    })
            if not move.line_ids:
                # Defensive: a date group with no matching-currency targets
                # would produce an empty move and fail the no-lines check.
                move.unlink()
                continue
            move.action_post()
            moves |= move
        if not moves:
            raise UserError(_(
                "Nothing was generated. Check that target currencies "
                "match the source line currencies and that target amounts "
                "are non-zero."
            ))
        return moves

    def _faap_mirror_for(self, stock_account):
        return self.env['jito.ledger.account'].search([
            ('statutory_account_id', '=', stock_account.id),
            ('company_id', '=', self.company_id.id),
            ('semantic_family', '=', 'faap'),
        ], limit=1)


class JitoMgtRegroupingTargetLine(models.Model):
    """One target distribution line of a regrouping.

    17.0.3.0.0 — amount mode (no more weights). The line carries the
    absolute amount routed to ``target_account_id`` in ``currency_id``,
    optionally tagged with ``partner_id`` and dated for its own
    ``date``. Per HLD §5.5, the per-currency sum of target amounts must
    equal the per-currency sum of source line amounts exactly.
    """

    _name = 'jito.mgt.regrouping.target.line'
    _description = 'Regrouping Target Distribution'
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)

    regrouping_id = fields.Many2one(
        comodel_name='jito.mgt.regrouping',
        required=True,
        ondelete='cascade',
        index=True,
    )
    company_id = fields.Many2one(
        related='regrouping_id.company_id',
        store=True,
        readonly=True,
    )

    target_account_id = fields.Many2one(
        comodel_name='jito.ledger.account',
        string='Target Account',
        required=True,
        domain="['|', ('semantic_family', 'in', ['mgt', 'faap']), ('is_clearing', '=', True)]",
    )
    partner_id = fields.Many2one(
        comodel_name='res.partner',
        string='Partner',
        help="Optional. When set, the partner is stamped on the generated "
             "MGT-side jito.ledger.move.line only — the FAAP-reversal line "
             "keeps the source line's partner to preserve statutory "
             "traceability.",
    )
    name = fields.Char(string='Label')

    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        required=True,
        default=lambda self: self.env.company.currency_id,
        help="Currency of `amount`. Must match the currency of at least "
             "one source line — amount mode allocates per-currency.",
    )
    amount = fields.Monetary(
        string='Amount',
        required=True,
        currency_field='currency_id',
        help="Absolute amount routed to this target. Per-currency, the "
             "sum across target lines must equal the sum of source line "
             "amounts in the same currency (FR-22 strict equality).",
    )
    date = fields.Date(
        string='Accounting Date',
        required=True,
        default=lambda self: self._default_target_date(),
        help="Per-target accounting date. Targets on different dates "
             "generate separate jito.ledger.move records (one per "
             "distinct date), each per-currency balanced.",
    )

    @api.model
    def _default_target_date(self):
        # Default to the parent regrouping's `date` when reachable
        # via context (Odoo passes the parent's record into the
        # One2many editing context).
        parent = self.env.context.get('default_regrouping_id')
        if parent:
            reg = self.env['jito.mgt.regrouping'].browse(parent)
            if reg.date:
                return reg.date
        return fields.Date.context_today(self)

    @api.constrains('amount')
    def _check_amount_nonzero(self):
        for line in self:
            if line.currency_id and line.currency_id.is_zero(line.amount):
                raise ValidationError(_(
                    "Target amount must be non-zero (line '%s').",
                    line.name or line.target_account_id.code or '?',
                ))

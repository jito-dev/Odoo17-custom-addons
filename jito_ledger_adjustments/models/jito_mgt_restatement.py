# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

from ..snapshot_schemas import snapshot_account_move_line, CURRENT_VERSION
from ..preview import render_preview_table


class JitoMgtRestatement(models.Model):
    """FR-06 — Management Restatement.

    Re-categorize the management meaning of a specific LL line (or set
    of LL lines) into a target MGT account. Generates a single balanced
    `jito.ledger.move(entry_type='mgt_restate')` plus
    `jito.ledger.trace` rows linking each generated line to its
    contributing LL source line(s).

    Difference from manual ext_adjustment: traceability is
    **mandatory** — restatement always emits trace rows that an auditor
    can query ("show me which statutory line drove this management
    line"). Manual ext_adjustment is freeform.

    Form flow:
      1. Pick a journal in the destination ledger (the journal carries
         the ledger via jito.ledger.journal.rel).
      2. Pick one or more LL `account.move.line` records as sources.
      3. Pick the target MGT account (must be MGT.* family).
      4. Optionally override the FAAP source representation (defaults to
         the FAAP mirror of the LL source's account, if available).
      5. Confirm — generates the balanced move + trace rows.
    """

    _name = 'jito.mgt.restatement'
    _description = 'Management Restatement (FR-06)'
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
    # 17.0.9.0.0 — needed for the Realization Monetary fields below
    # (delta / allocated / remaining) that report in company currency.
    company_currency_id = fields.Many2one(
        comodel_name='res.currency',
        related='company_id.currency_id',
        store=True,
        readonly=True,
    )

    source_line_ids = fields.Many2many(
        comodel_name='account.move.line',
        relation='jito_mgt_restatement_source_line_rel',
        column1='restatement_id',
        column2='line_id',
        string='Statutory Source Lines',
        required=True,
        help="The LL lines whose management meaning is being restated.",
    )
    target_account_id = fields.Many2one(
        comodel_name='jito.ledger.account',
        string='Target Management Account',
        required=True,
        domain="[('company_id', '=', company_id), "
               "('semantic_family', '=', 'mgt')]",
        help="The MGT.* account that captures the restated management "
             "meaning. Must be in the same company as the journal.",
    )

    # 17.0.7.0.0 — Match an existing entry on the Final Destination
    # account instead of routing through the CLR clearing account.
    #
    # When set, the restatement uses the same-currency path (no CLR
    # line generated), auto-fills ``target_amount`` from the picked
    # line's ``amount_currency``, and reconciles the new MGT-target
    # line against the picked entry after post — so the restatement
    # is fully matched at creation time, no later manual clearing
    # needed.
    #
    # Constraint: only same-currency matches are supported. For
    # cross-currency restatements, leave this field empty and use the
    # FX Clearing flow.
    destination_line_id = fields.Many2one(
        comodel_name='jito.ledger.move.line',
        string='Matched Destination Entry',
        domain="[('account_id', '=', target_account_id), "
               "('move_state', '=', 'posted'), "
               "('amount_residual_currency', '!=', 0), "
               "('company_id', '=', company_id)]",
        tracking=True,
        help="Optionally pick an existing entry on the Final Destination "
             "account (e.g. a real 'inbound 8000 USDT' inflow) to match "
             "this restatement against. When set:\n"
             "  • Final Amount auto-fills from the picked entry\n"
             "  • Effective FX Rate auto-computes from source / target\n"
             "  • The new MGT-target line is reconciled with the picked "
             "entry on Post (signs auto-align — no later manual clearing "
             "of the matched side).\n\n"
             "Same-currency match: no FX Clearing required. Source and "
             "destination must have opposite signs (one debit, one "
             "credit) so the move balances and the pair reconciles.\n"
             "Cross-currency match (17.0.7.3.2): FX Clearing still "
             "required for per-currency balance. The full 4-line "
             "structure (FAAP-reversal + CLR-src + MGT-target + "
             "CLR-tgt) is generated; the MGT-target sign is auto-"
             "flipped against the destination so the reconcile works "
             "regardless of which leg of the source you pick.",
    )

    # ---- Realization allocation (17.0.9.0.0) ----------------------------
    #
    # Cross-currency Restatement calibrates its CLR pair on the
    # destination's market value. The source's LL projection lands at
    # the LL posting rate, leaving a residual on the FAAP mirror equal
    # to the company-currency gap (e.g. 10k EUR × 1.30 = 13k USD vs
    # 12k USDT × 1.00 = 12k USD → 1k USD residual). This block lets
    # the user attribute that residual to P&L accounts: conversion
    # fees, FX loss/gain, etc.

    realization_line_ids = fields.One2many(
        comodel_name='jito.mgt.restatement.realization',
        inverse_name='restatement_id',
        string='Realization Allocation',
        copy=False,
        help="Allocation of the company-currency delta between the "
             "source's market value and the target's market value to "
             "P&L accounts. Empty when no delta exists (same-currency "
             "or rate-aligned cross-currency).",
    )
    realization_delta = fields.Monetary(
        string='Realization Delta',
        compute='_compute_realization_delta',
        currency_field='company_currency_id',
        help="Signed company-currency gap between source-market value "
             "and target-market value. Positive = loss (source > "
             "target). Must be fully allocated across "
             "``realization_line_ids`` before posting (or zero, in "
             "which case the tab is hidden).",
    )
    realization_allocated = fields.Monetary(
        string='Allocated',
        compute='_compute_realization_remaining',
        currency_field='company_currency_id',
    )
    realization_remaining = fields.Monetary(
        string='Remaining',
        compute='_compute_realization_remaining',
        currency_field='company_currency_id',
    )
    realization_is_complete = fields.Boolean(
        compute='_compute_realization_remaining',
        help="True when the delta is zero OR fully allocated. Drives "
             "the form's per-section validation badge.",
    )

    @api.depends(
        'source_line_ids',
        'source_line_ids.debit',
        'source_line_ids.credit',
        'destination_line_id',
        'destination_line_id.balance',
        'destination_line_id.amount_currency',
        'is_fx_conversion', 'target_currency_id', 'target_amount',
        'date', 'company_id',
    )
    def _compute_realization_delta(self):
        for rec in self:
            rec.realization_delta = rec._calc_realization_delta()

    def _calc_realization_delta(self):
        """Return the signed company-currency delta
        ``src_market - tgt_market``. Zero when not cross-currency or
        when sources / target aren't yet known.

        **Anchoring on frozen company-currency columns** (17.0.9.0.2):
        the source side reads ``line.debit - line.credit`` directly
        from the LL ``account.move.line`` records — same frozen
        company-currency values the combined LL+NL+EXT GL aggregates
        via ``jito.ledger.statutory.view``. Recomputing via
        ``_convert`` at the restatement date is wrong because the
        market rate may have moved between the bill's posting date
        and the restatement date, producing a delta that doesn't
        match the actual FAAP residual.

        For the target, matched mode reads ``destination_line_id.balance``
        (also frozen at posting). Unmatched mode falls back to
        ``_convert`` of ``target_amount`` since no destination move
        exists yet.
        """
        self.ensure_one()
        if not self.is_fx_conversion or not self.source_line_ids:
            return 0.0
        company_currency = self.company_id.currency_id
        if not company_currency:
            return 0.0

        # Source side — use LL's frozen company-currency value.
        src_market = abs(sum(
            (line.debit or 0.0) - (line.credit or 0.0)
            for line in self.source_line_ids
        ))
        if not src_market:
            return 0.0

        # Target side — frozen ``balance`` if matched, else market
        # conversion of the user-entered ``target_amount``.
        if self.destination_line_id:
            tgt_market = abs(self.destination_line_id.balance or 0.0)
        else:
            tgt_signed = self.target_amount or 0.0
            tgt_currency = self.target_currency_id
            if not tgt_currency or not tgt_signed:
                return 0.0
            if tgt_currency == company_currency:
                tgt_market = abs(tgt_signed)
            else:
                as_of = self.date or fields.Date.context_today(self)
                tgt_market = abs(tgt_currency._convert(
                    abs(tgt_signed), company_currency,
                    self.company_id, as_of,
                ))
        # Positive = source > target (loss); negative = gain.
        return src_market - tgt_market

    @api.depends('realization_delta', 'realization_line_ids.amount')
    def _compute_realization_remaining(self):
        for rec in self:
            allocated = sum(rec.realization_line_ids.mapped('amount'))
            rec.realization_allocated = allocated
            rec.realization_remaining = (rec.realization_delta or 0.0) - allocated
            ccy = rec.company_currency_id
            if not ccy:
                rec.realization_is_complete = True
                continue
            if ccy.is_zero(rec.realization_delta):
                rec.realization_is_complete = True
            else:
                rec.realization_is_complete = ccy.is_zero(rec.realization_remaining)

    def action_realization_fill_remainder(self):
        """Single-click: add one line absorbing the entire remaining
        delta. Picks a sensible default account if any expense/income
        account exists for the company; otherwise opens a fresh row
        for the user to choose.
        """
        self.ensure_one()
        if self.company_currency_id.is_zero(self.realization_remaining):
            return False
        Realization = self.env['jito.mgt.restatement.realization']
        # No default account guessing in v1 — just open an empty row
        # with the amount pre-filled. The form's UI prompts the user
        # to pick an account.
        Realization.create({
            'restatement_id': self.id,
            'name': _("FX realization"),
            'amount': self.realization_remaining,
        })
        return True

    date = fields.Date(
        string='Date',
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )
    reason = fields.Char(
        string='Reason',
        tracking=True,
        help="Why this restatement is being made. Captured for audit.",
    )

    generated_move_id = fields.Many2one(
        comodel_name='jito.ledger.move',
        string='Generated Move',
        readonly=True,
        copy=False,
        help="The jito.ledger.move(entry_type=mgt_restate) produced by "
             "this restatement on confirmation.",
    )
    # 17.0.7.3.0 — surface the generated move's lines as their own
    # field so the form can drill into them without round-tripping
    # through generated_move_id. Read-only — the lines are owned by
    # the move; the restatement just exposes them for visibility.
    generated_line_ids = fields.One2many(
        related='generated_move_id.line_ids',
        string='Generated Journal Items',
        readonly=True,
    )

    # ---- Cross-currency conversion (17.0.5.0.0) -------------------------
    #
    # FX is automatic: when ``target_account_id.currency_id`` differs
    # from the (homogeneous) source-line currency, the restatement enters
    # FX mode. The user provides the **final amount in target currency**
    # (``target_amount``); the rate is back-computed as
    # ``abs(target_amount) / abs(net source amount)``.
    #
    # Each source line then produces four parallel lines so per-currency
    # balance holds within the single generated move (HLD §8.3):
    #
    #   src_currency:  FAAP_reversal(-X)   + FX_clearing(+X)
    #   tgt_currency:  FX_clearing(-X·R)   + MGT_target(+X·R)
    #
    # The FX clearing account then naturally holds the FX residual
    # across currencies; rate fluctuations show up at report time via
    # FR-23 presentation translation — **no posted FX revaluation JE**
    # (per HLD line 60 / FR-23). This keeps the cross-currency feature
    # consistent with the HLD's "FX is presentation, not posting" rule.
    #
    # The rate is tied to *this* move only — there's no global
    # currency-rate side-effect. Two restatements on the same day can
    # legitimately use different rates.

    target_currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Target Currency',
        compute='_compute_target_currency_id',
        store=True,
        readonly=True,
        help="Derived from the Final Destination account's currency "
             "(falls back to the source-line currency, then company "
             "currency). Cross-currency conversion auto-activates when "
             "this differs from the source-line currency.",
    )
    is_fx_conversion = fields.Boolean(
        string='Cross-Currency Conversion',
        compute='_compute_is_fx_conversion',
        store=True,
        help="True when sources and target are in different currencies. "
             "Drives the four-line FAAP/FX-clearing/MGT/FX-clearing "
             "pattern on Post.",
    )
    target_amount = fields.Monetary(
        string='Final Amount',
        currency_field='target_currency_id',
        help="The actual amount you want recorded on the MGT target in "
             "the target currency (e.g. '10800' USDC for an EUR→USDC "
             "conversion). The effective FX rate is back-computed from "
             "this and the source net. Sign follows the source net "
             "automatically — enter the magnitude.",
    )
    fx_clearing_account_id = fields.Many2one(
        comodel_name='jito.ledger.account',
        string='FX Clearing Account',
        domain="[('company_id', '=', company_id), "
               "('semantic_family', '=', 'clr')]",
        tracking=True,
        help="CLR.* clearing account that holds both sides of the "
             "conversion. After posting, this account carries +X in the "
             "source currency and -X·R in the target currency — netting "
             "to zero in company currency at rate R, with later rate "
             "movements appearing as FX residual at report time only.",
    )
    effective_fx_rate = fields.Float(
        string='Effective FX Rate',
        compute='_compute_effective_fx_rate',
        digits=(16, 8),
        store=True,
        help="`abs(target_amount) / abs(source_net)`. Computed live; "
             "tied to this single restatement (no global rate update).",
    )

    @api.depends('target_account_id.currency_id', 'source_line_ids',
                 'company_id')
    def _compute_target_currency_id(self):
        for record in self:
            account_cur = record.target_account_id.currency_id
            if account_cur:
                record.target_currency_id = account_cur
                continue
            src = record._source_currency()
            record.target_currency_id = (
                src or record.company_id.currency_id
                or record.env.company.currency_id
            )

    @api.depends('target_currency_id', 'source_line_ids')
    def _compute_is_fx_conversion(self):
        for record in self:
            src = record._source_currency()
            record.is_fx_conversion = bool(
                src and record.target_currency_id
                and src.id != record.target_currency_id.id
            )

    @api.depends('is_fx_conversion', 'target_amount', 'source_line_ids')
    def _compute_effective_fx_rate(self):
        for record in self:
            if not record.is_fx_conversion or not record.target_amount:
                record.effective_fx_rate = 0.0
                continue
            src_net = record._source_net_amount()
            if not src_net:
                record.effective_fx_rate = 0.0
                continue
            record.effective_fx_rate = abs(record.target_amount) / abs(src_net)

    @api.onchange('target_account_id', 'source_line_ids')
    def _onchange_clear_target_amount_when_no_fx(self):
        """If switching to a target account in the same currency as
        sources, drop any leftover ``target_amount`` so it doesn't
        confuse the constraint on Post.
        """
        if not self.is_fx_conversion:
            self.target_amount = 0.0

    @api.onchange('destination_line_id')
    def _onchange_destination_line_id(self):
        """Auto-fill ``target_amount`` from the matched destination
        entry (17.0.7.0.0). The magnitude is taken; the sign on the
        generated MGT line is driven by source_net just like the
        manual-entry path.
        """
        if self.destination_line_id:
            self.target_amount = abs(self.destination_line_id.amount_currency)

    @api.onchange('target_account_id')
    def _onchange_clear_destination_when_target_changes(self):
        """Drop any prior matched entry when the user picks a
        different Final Destination — the previous match would now
        point at the wrong account.
        """
        if self.destination_line_id and \
                self.destination_line_id.account_id != self.target_account_id:
            self.destination_line_id = False

    # ---- preview (17.0.2.2.0) -------------------------------------------

    preview_html = fields.Html(
        string='Preview',
        compute='_compute_preview_html',
        sanitize=False,
        readonly=True,
    )

    @api.depends('source_line_ids', 'target_account_id',
                 'is_fx_conversion', 'target_currency_id',
                 'target_amount', 'effective_fx_rate',
                 'fx_clearing_account_id', 'date')
    def _compute_preview_html(self):
        for record in self:
            record.preview_html = render_preview_table(
                record._build_preview_lines()
            )

    def _build_preview_lines(self):
        """Per source:
          * Same-currency (default): FAAP-reversal + MGT target line.
          * FX conversion: FAAP-reversal + FX-clearing (src side) +
            MGT target (tgt × rate) + FX-clearing (tgt side).
        """
        self.ensure_one()
        lines = []
        if not self.target_account_id or not self.source_line_ids:
            return lines
        fx_active = self.is_fx_conversion and self.target_currency_id and (
            self.fx_clearing_account_id
        )
        rate = self.effective_fx_rate if fx_active else 0.0
        if fx_active and not rate:
            return lines  # cannot preview without target_amount
        for src in self.source_line_ids:
            src_signed = src.amount_currency or (src.debit - src.credit)
            src_currency = src.currency_id or src.company_id.currency_id
            faap_account = self._faap_mirror_for(src.account_id)
            faap_code = (faap_account and faap_account.code) \
                or ('FAAP-mirror-of-' + src.account_id.code)
            # FAAP-reversal (always in source currency)
            lines.append({
                'account_code': faap_code,
                'name': _("Restate from %s") % src.account_id.code,
                'currency_symbol': src_currency.symbol,
                'debit':  -src_signed if src_signed < 0 else 0.0,
                'credit':  src_signed if src_signed > 0 else 0.0,
            })
            if not fx_active:
                lines.append({
                    'account_code': self.target_account_id.code,
                    'name': _("Restate to %s") % self.target_account_id.code,
                    'currency_symbol': src_currency.symbol,
                    'debit':  src_signed if src_signed > 0 else 0.0,
                    'credit': -src_signed if src_signed < 0 else 0.0,
                })
                continue
            # FX path — emit FX clearing on both sides plus MGT target.
            tgt_currency = self.target_currency_id
            tgt_signed = tgt_currency.round(src_signed * rate)
            # FX clearing line in source currency (balances source side
            # against the FAAP reversal).
            lines.append({
                'account_code': self.fx_clearing_account_id.code,
                'name': _("FX clearing (%s side)") % src_currency.name,
                'currency_symbol': src_currency.symbol,
                'debit':  src_signed if src_signed > 0 else 0.0,
                'credit': -src_signed if src_signed < 0 else 0.0,
            })
            # MGT target line in target currency.
            lines.append({
                'account_code': self.target_account_id.code,
                'name': _("Restate to %s (FX %s→%s @ %s)") % (
                    self.target_account_id.code,
                    src_currency.name, tgt_currency.name, rate,
                ),
                'currency_symbol': tgt_currency.symbol,
                'debit':  tgt_signed if tgt_signed > 0 else 0.0,
                'credit': -tgt_signed if tgt_signed < 0 else 0.0,
            })
            # FX clearing line in target currency (balances target side).
            lines.append({
                'account_code': self.fx_clearing_account_id.code,
                'name': _("FX clearing (%s side)") % tgt_currency.name,
                'currency_symbol': tgt_currency.symbol,
                'debit':  -tgt_signed if tgt_signed < 0 else 0.0,
                'credit':  tgt_signed if tgt_signed > 0 else 0.0,
            })
        return lines

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if 'journal_id' in fields_list and not res.get('journal_id'):
            jid = self.env['jito.mgt.bridging']._resolve_default_adjustments_journal()
            if jid:
                res['journal_id'] = jid
        return res

    # ---- workflow --------------------------------------------------------

    def action_post(self):
        """Generate the balanced move + trace rows; transition to posted."""
        for record in self:
            if record.state != 'draft':
                raise UserError(_(
                    "Only draft restatements can be posted (record '%s' "
                    "is %s).", record.name, record.state,
                ))
            if not record.source_line_ids:
                raise UserError(_(
                    "Pick at least one statutory source line."
                ))
            if record.name == _('New'):
                seq = self.env['ir.sequence'].with_company(
                    record.company_id
                ).next_by_code('jito.mgt.restatement') or _('New')
                record.name = seq
            move = record._generate_move()
            record.write({
                'state': 'posted',
                'generated_move_id': move.id,
            })
            record.message_post(body=_(
                "Restatement posted as %s.", move.display_name,
            ))
        return True

    def _generate_move(self):
        """Create the jito.ledger.move with balanced lines + trace rows."""
        self.ensure_one()
        Move = self.env['jito.ledger.move']
        Line = self.env['jito.ledger.move.line']
        Trace = self.env['jito.ledger.trace']

        # Group source lines by (currency, side, FAAP mirror) so we can
        # emit one consolidated line per source-bucket.
        # For each source LL line: a pair of parallel-ledger lines, one
        # reversing the FAAP projection (debit FAAP if source was credit,
        # vice versa), one posting to the MGT target.
        single_source_move = (
            self.source_line_ids[0].move_id
            if self.source_line_ids
            and len(self.source_line_ids.mapped('move_id')) == 1
            else self.env['account.move']
        )
        move = Move.create({
            'journal_id': self.journal_id.id,
            'date': self.date,
            'entry_type': 'mgt_restate',
            'ref': _("Restatement %s") % self.name,
            'state': 'draft',
            'name': _('New'),
            'reason': self.reason,
            'source_move_id': single_source_move.id if single_source_move else False,
            'adjustment_origin': '%s,%s' % (self._name, self.id),
        })

        # 17.0.7.0.0 — matched-destination mode tracks the generated
        # MGT-target line(s) for post-action reconciliation against
        # the picked destination entry.
        # 17.0.7.1.0 — matched mode now coexists with the FX path:
        # cross-currency matched still flows through the 4-line FAAP/
        # CLR-src/MGT-target/CLR-tgt structure (per-currency balance
        # is non-negotiable), but the MGT-target side is auto-cleared
        # by reconciling with the matched destination on Post.
        matched_mode = bool(self.destination_line_id)
        mgt_target_lines = self.env['jito.ledger.move.line']

        fx_active = self.is_fx_conversion
        rate = self.effective_fx_rate if fx_active else 0.0
        tgt_currency = self.target_currency_id if fx_active else None
        if fx_active and not rate:
            raise UserError(_(
                "Cannot post: the effective FX rate is zero. Set the "
                "Final Amount in the target currency before posting."
            ))
        company_currency = self.company_id.currency_id
        for src in self.source_line_ids:
            faap_account = self._faap_mirror_for(src.account_id)
            if not faap_account:
                raise UserError(_(
                    "No FAAP mirror found for stock account '%s'. Run "
                    "Configuration → Sync FAAP Mirrors first.",
                    src.account_id.code,
                ))
            src_signed = src.amount_currency or (src.debit - src.credit)
            src_currency = src.currency_id or src.company_id.currency_id

            # 17.0.10.0.0 — pre-compute the per-source company-currency
            # anchor for calibrated FX moves. All four FX lines get an
            # explicit ``balance`` equal to ±anchor (sign follows
            # amount_currency) so the CLR pair nets to zero in company
            # currency and the move balances cleanly under the new
            # ``_check_balanced_in_company_currency`` constraint.
            #
            # Same-currency restatements omit the explicit balance —
            # the default ``_compute_balance`` translates each line at
            # ``line.date`` and naturally balances within the single
            # currency.
            if fx_active:
                if matched_mode:
                    tgt_for_anchor = self.destination_line_id.amount_currency
                else:
                    tgt_for_anchor = tgt_currency.round(src_signed * rate)
                if tgt_currency and tgt_currency != company_currency:
                    per_source_anchor = abs(tgt_currency._convert(
                        tgt_for_anchor, company_currency,
                        self.company_id, self.date,
                    ))
                else:
                    per_source_anchor = abs(tgt_for_anchor)
            else:
                per_source_anchor = 0.0

            def _balance_for(amount):
                """Return calibrated company-currency balance for an
                FX-active line: sign follows amount_currency, magnitude
                = per-source anchor. Returns 0.0 outside FX mode (the
                default ``_compute_balance`` then takes over).
                """
                if not fx_active or not amount:
                    return None
                return per_source_anchor if amount > 0 else -per_source_anchor

            # FAAP-reversal — always in source currency, opposite sign.
            faap_vals = {
                'move_id': move.id,
                'account_id': faap_account.id,
                'name': _("Restate from %s") % src.account_id.code,
                'currency_id': src_currency.id,
                'amount_currency': -src_signed,
            }
            faap_bal = _balance_for(-src_signed)
            if faap_bal is not None:
                faap_vals['balance'] = faap_bal
            faap_line = Line.create(faap_vals)
            generated_lines = [faap_line]

            if not fx_active:
                # Plain same-currency restatement.
                mgt_line = Line.create({
                    'move_id': move.id,
                    'account_id': self.target_account_id.id,
                    'name': _("Restate to %s") % self.target_account_id.code,
                    'currency_id': src_currency.id,
                    'amount_currency': src_signed,
                })
                generated_lines.append(mgt_line)
                if matched_mode:
                    mgt_target_lines |= mgt_line
            else:
                # FX path. Four lines per source — balance per currency.
                #
                # Sign convention:
                #   * Unmatched: MGT-target follows the source sign
                #     (``tgt_signed = src_signed * rate``); CLR-tgt is
                #     its mirror.
                #   * Matched (17.0.7.3.2): MGT-target is forced to
                #     the **opposite sign** of the destination entry
                #     so the two can be reconciled on Post; CLR-tgt
                #     mirrors that flipped sign. Magnitude is the same
                #     in both cases (``abs(target_amount)``), so the
                #     effective FX rate is preserved either way.
                #
                # All four lines are always emitted so the matched
                # case still posts a full "push from CLR to target"
                # entry (matching the unmatched flow's shape).
                if matched_mode:
                    dest_signed = self.destination_line_id.amount_currency
                    tgt_signed = tgt_currency.round(-dest_signed)
                else:
                    tgt_signed = tgt_currency.round(src_signed * rate)
                clearing_src = Line.create({
                    'move_id': move.id,
                    'account_id': self.fx_clearing_account_id.id,
                    'name': _("FX clearing (%s)") % src_currency.name,
                    'currency_id': src_currency.id,
                    'amount_currency': src_signed,
                    'balance': _balance_for(src_signed),
                })
                mgt_line = Line.create({
                    'move_id': move.id,
                    'account_id': self.target_account_id.id,
                    'name': _("Restate to %s (FX %s→%s @ %s)") % (
                        self.target_account_id.code,
                        src_currency.name, tgt_currency.name, rate,
                    ),
                    'currency_id': tgt_currency.id,
                    'amount_currency': tgt_signed,
                    'balance': _balance_for(tgt_signed),
                })
                clearing_tgt = Line.create({
                    'move_id': move.id,
                    'account_id': self.fx_clearing_account_id.id,
                    'name': _("FX clearing (%s)") % tgt_currency.name,
                    'currency_id': tgt_currency.id,
                    'amount_currency': -tgt_signed,
                    'balance': _balance_for(-tgt_signed),
                })
                generated_lines.extend([clearing_src, mgt_line, clearing_tgt])
                if matched_mode:
                    # Track for post-action reconciliation against
                    # destination_line_id (signs are opposite by
                    # construction above).
                    mgt_target_lines |= mgt_line

            for line in generated_lines:
                Trace.create({
                    'parallel_line_id': line.id,
                    'source_line_id': src.id,
                    'source_snapshot': snapshot_account_move_line(src),
                    'snapshot_version': CURRENT_VERSION,
                    'kind': 'derives_from',
                    'weight': 1.0,
                })

        # 17.0.9.0.0 — realization allocation. When the user dedicated
        # a slice of the company-currency FX delta to P&L accounts,
        # emit one consolidated counter on the source's FAAP mirror
        # (which cancels the residual in the LL+NL+EXT combined view)
        # plus one P&L line per realization row. All lines are in
        # company currency and sum to zero — per-currency balance and
        # move balance both hold.
        company_currency = self.company_id.currency_id
        total_realization = sum(self.realization_line_ids.mapped('amount'))
        if (self.realization_line_ids and company_currency
                and not company_currency.is_zero(total_realization)):
            first_src = self.source_line_ids[0]
            first_faap = self._faap_mirror_for(first_src.account_id)
            if first_faap:
                Line.create({
                    'move_id': move.id,
                    'account_id': first_faap.id,
                    'name': _("Realization counter (FX delta)"),
                    'currency_id': company_currency.id,
                    'amount_currency': -total_realization,
                    'balance': -total_realization,
                })
                for r in self.realization_line_ids:
                    Line.create({
                        'move_id': move.id,
                        'account_id': r.account_id.id,
                        'name': r.name or _("FX realization"),
                        'currency_id': company_currency.id,
                        'amount_currency': r.amount,
                        'balance': r.amount,
                    })

        # Post the move (runs balance constraint + period-lock check)
        move.action_post()

        if matched_mode:
            # 17.0.7.2.0 — split behavior:
            #
            # * Same-currency matched: the generated MGT-target line
            #   is paired with the destination via partial reconcile.
            #   Requires opposite signs (enforced by
            #   _check_destination_line). If signs don't align,
            #   fall back gracefully — the trace + chatter note still
            #   capture the match for audit.
            # * Cross-currency matched: no target-side line was
            #   generated; nothing to reconcile. The link is captured
            #   by the chatter note + the trace rows below.
            if mgt_target_lines:
                try:
                    (mgt_target_lines | self.destination_line_id)._reconcile()
                except UserError as e:
                    move.message_post(body=_(
                        "Matched destination reconciliation skipped: %s "
                        "Trace links source → restatement → destination "
                        "for audit; pair the lines manually via the "
                        "reconciliation widget if needed.",
                        str(e),
                    ))
            move.message_post(body=_(
                "Matched destination: %s (entry on %s).",
                self.destination_line_id.display_name or
                    ('line #%s' % self.destination_line_id.id),
                self.target_account_id.code,
            ))
        return move

    def _faap_mirror_for(self, stock_account):
        """Look up the jito.ledger.account FAAP mirror for a stock
        account.account, scoped to this restatement's company.
        """
        return self.env['jito.ledger.account'].search([
            ('statutory_account_id', '=', stock_account.id),
            ('company_id', '=', self.company_id.id),
            ('semantic_family', '=', 'faap'),
        ], limit=1)

    # ---- FX helpers (17.0.4.0.0) ----------------------------------------

    def _source_currency(self):
        """Return the single currency shared by all source lines, or
        None if there are no sources / sources are mixed currency.
        """
        self.ensure_one()
        currency_ids = set()
        for line in self.source_line_ids:
            cur = line.currency_id or line.company_id.currency_id
            if cur:
                currency_ids.add(cur.id)
        if len(currency_ids) != 1:
            return None
        return self.env['res.currency'].browse(currency_ids.pop())

    def _source_net_amount(self):
        """Return the signed sum of ``amount_currency`` across source
        lines (positive = net debit, negative = net credit). Used to
        back-compute the FX rate from ``target_amount`` and to drive
        sign of generated MGT lines.
        """
        self.ensure_one()
        return sum(
            line.amount_currency or (line.debit - line.credit)
            for line in self.source_line_ids
        )

    # ---- FX validation --------------------------------------------------

    @api.constrains(
        'is_fx_conversion', 'target_currency_id',
        'fx_clearing_account_id', 'target_amount',
        'source_line_ids', 'state', 'destination_line_id',
    )
    def _check_fx_conversion(self):
        for record in self:
            # 17.0.7.1.0 — cross-currency matched mode still needs a
            # CLR account (per-currency balance must hold within the
            # generated move; only the MGT-target side is auto-cleared
            # by the match). Same-currency matched mode short-circuits
            # because is_fx_conversion is False.
            if not record.is_fx_conversion:
                continue
            if not record.fx_clearing_account_id:
                raise ValidationError(_(
                    "Cross-Currency Conversion requires an FX Clearing "
                    "Account (CLR.* family) so per-currency balance can "
                    "hold within a single generated move."
                ))
            if record.fx_clearing_account_id.semantic_family != 'clr':
                raise ValidationError(_(
                    "FX Clearing Account '%s' must be a CLR.* "
                    "(clearing) account; got semantic_family='%s'.",
                    record.fx_clearing_account_id.code,
                    record.fx_clearing_account_id.semantic_family,
                ))
            src = record._source_currency()
            if not src and record.source_line_ids:
                raise ValidationError(_(
                    "Cross-Currency Conversion requires all source lines "
                    "to share one currency. Use plain restatement per "
                    "currency, or split into multiple restatements."
                ))
            if record.state != 'draft':
                if not record.target_amount:
                    raise ValidationError(_(
                        "Cross-Currency Conversion requires a non-zero "
                        "Final Amount in the target currency before "
                        "posting."
                    ))
                if not record._source_net_amount():
                    raise ValidationError(_(
                        "Cannot back-compute the FX rate: the net source "
                        "amount is zero. Cross-currency restatement of "
                        "perfectly-canceling sources is undefined."
                    ))

    @api.constrains('destination_line_id', 'target_account_id',
                    'source_line_ids')
    def _check_destination_line(self):
        """Validate the matched-destination scenario.

        17.0.7.0.0 introduced same-currency matched mode.
        17.0.7.1.0 extends it to cross-currency matched: the destination
        currency dictates the target side; an FX Clearing account is
        still required (per-currency balance must hold within the move),
        but the MGT-target side gets auto-reconciled with the matched
        entry on Post.
        """
        for record in self:
            if not record.destination_line_id:
                continue
            dest = record.destination_line_id
            if dest.account_id != record.target_account_id:
                raise ValidationError(_(
                    "The matched destination entry must be on the Final "
                    "Destination account '%s' (got '%s').",
                    record.target_account_id.code, dest.account_id.code,
                ))
            if dest.move_state != 'posted':
                raise ValidationError(_(
                    "The matched destination entry must be on a posted "
                    "move (entry %s is %s).", dest.id, dest.move_state,
                ))
            # 17.0.7.2.0 — reconcilable is only required for same-
            # currency matched (where we actually call _reconcile).
            # Cross-currency matched skips target-side lines and links
            # via trace + chatter note, so target account doesn't need
            # to be reconcilable.
            src = record._source_currency()
            dest_cur = dest.currency_id
            same_currency = bool(src and dest_cur and src.id == dest_cur.id)
            if same_currency and not record.target_account_id.reconcile:
                raise ValidationError(_(
                    "Target account '%s' is not marked reconcilable; "
                    "enable 'Allow Reconciliation' on it before "
                    "same-currency matching to an existing entry.",
                    record.target_account_id.code,
                ))
            # 17.0.7.2.0 — same-currency matched needs source / dest
            # to have OPPOSITE signs so the auto-reconcile works (one
            # debit, one credit). Cross-currency matched has no such
            # constraint because no target-side line is generated.
            if same_currency:
                src_net = record._source_net_amount()
                dest_amt = dest.amount_currency
                if src_net and dest_amt and (src_net > 0) == (dest_amt > 0):
                    raise ValidationError(_(
                        "Same-currency matched restatement requires the "
                        "source and destination to have OPPOSITE signs "
                        "(one debit, one credit) so they can be "
                        "reconciled. Source net is %s, destination is "
                        "%s — both on the same side. Pick the other "
                        "leg of the source move, or pick a destination "
                        "with the opposite sign.",
                        src_net, dest_amt,
                    ))

    @api.constrains(
        'realization_delta', 'realization_line_ids',
        'realization_line_ids.amount', 'state',
    )
    def _check_realization_complete(self):
        """On Post, the realization delta must be fully allocated
        (17.0.9.0.0). Zero delta or empty allocation is fine when the
        delta is zero — but a non-zero delta must net to zero across
        the realization rows so the FAAP residual is fully absorbed
        into P&L.
        """
        for record in self:
            if record.state == 'draft':
                continue
            if not record.is_fx_conversion:
                continue
            ccy = record.company_currency_id
            if not ccy or ccy.is_zero(record.realization_delta):
                continue
            if not ccy.is_zero(record.realization_remaining):
                raise ValidationError(_(
                    "Realization not fully allocated. The FX delta is "
                    "%s, of which %s remains unallocated. Add P&L "
                    "rows in the Realization tab so the total matches "
                    "the delta, then re-post. "
                    "(Or hit ‘Fill remainder’ to add one row with the "
                    "full residual.)",
                    ccy.format(record.realization_delta),
                    ccy.format(record.realization_remaining),
                ))

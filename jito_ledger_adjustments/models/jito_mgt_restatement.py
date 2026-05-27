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

        fx_active = self.is_fx_conversion
        rate = self.effective_fx_rate if fx_active else 0.0
        tgt_currency = self.target_currency_id if fx_active else None
        if fx_active and not rate:
            raise UserError(_(
                "Cannot post: the effective FX rate is zero. Set the "
                "Final Amount in the target currency before posting."
            ))
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

            # FAAP-reversal — always in source currency, opposite sign.
            faap_line = Line.create({
                'move_id': move.id,
                'account_id': faap_account.id,
                'name': _("Restate from %s") % src.account_id.code,
                'currency_id': src_currency.id,
                'amount_currency': -src_signed,
            })
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
            else:
                # FX path. Four lines per source — balance per currency.
                tgt_signed = tgt_currency.round(src_signed * rate)
                clearing_src = Line.create({
                    'move_id': move.id,
                    'account_id': self.fx_clearing_account_id.id,
                    'name': _("FX clearing (%s)") % src_currency.name,
                    'currency_id': src_currency.id,
                    'amount_currency': src_signed,
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
                })
                clearing_tgt = Line.create({
                    'move_id': move.id,
                    'account_id': self.fx_clearing_account_id.id,
                    'name': _("FX clearing (%s)") % tgt_currency.name,
                    'currency_id': tgt_currency.id,
                    'amount_currency': -tgt_signed,
                })
                generated_lines.extend([clearing_src, mgt_line, clearing_tgt])

            for line in generated_lines:
                Trace.create({
                    'parallel_line_id': line.id,
                    'source_line_id': src.id,
                    'source_snapshot': snapshot_account_move_line(src),
                    'snapshot_version': CURRENT_VERSION,
                    'kind': 'derives_from',
                    'weight': 1.0,
                })

        # Post the move (runs balance constraint + period-lock check)
        move.action_post()
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
        'source_line_ids', 'state',
    )
    def _check_fx_conversion(self):
        for record in self:
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
